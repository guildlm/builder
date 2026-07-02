"""GuildLM Builder — an agentic Go project generator.

The honest thesis: a 7B coder model does not reliably one-shot a working
backend. An *agent loop* that plans files, generates them, then compiles and
tests with a real toolchain — feeding the errors back for targeted fixes — does
produce working code. This module implements that loop.

The loop is model-pluggable via the ``Coder`` protocol. ``OpenAICoder`` talks to
any OpenAI-compatible endpoint (Ollama, vLLM, OpenAI itself); ``FakeCoder`` is a
deterministic stand-in for tests.

Run ``guildlm-build --spec spec.yaml --out ./generated`` to drive it.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol, Sequence

import yaml

# --------------------------------------------------------------------------- #
# Spec & planning
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class FileSpec:
    """A single target file the generator must produce."""

    path: str
    purpose: str


@dataclasses.dataclass(frozen=True)
class Spec:
    """A whole-project specification, typically loaded from YAML."""

    name: str
    description: str
    files: tuple[FileSpec, ...]
    language: str = "go"
    go_module: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Spec":
        files = tuple(
            FileSpec(path=f["path"], purpose=f["purpose"])
            for f in data.get("files", [])
        )
        return cls(
            name=data["name"],
            description=data["description"],
            language=data.get("language", "go"),
            go_module=data.get("go_module", ""),
            files=files,
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Spec":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(yaml.safe_load(fh))


@dataclasses.dataclass(frozen=True)
class FileTask:
    """A planned unit of work: produce ``spec.path`` fulfilling ``spec.purpose``."""

    index: int
    spec: FileSpec


def plan(spec: Spec) -> list[FileTask]:
    """Turn a Spec into an ordered list of FileTasks.

    This is intentionally pure and deterministic so it is unit-testable. The
    ordering is the spec order, which lets earlier files (e.g. ``go.mod``,
    models) become context for later ones.
    """
    return [FileTask(index=i, spec=fs) for i, fs in enumerate(spec.files)]


# --------------------------------------------------------------------------- #
# Code extraction
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(
    r"```(?:go|golang|mod|yaml|markdown|md|text)?\s*\n(.*?)```",
    re.DOTALL,
)


def extract_code(model_output: str) -> str:
    """Pull source code out of a model response.

    Strategy:
      1. If there is a fenced code block, return the contents of the first one.
         (Models love to wrap code in ```go ... ``` and add prose around it.)
      2. Otherwise assume the whole response is already code and return it
         trimmed.
    """
    match = _FENCE_RE.search(model_output)
    if match:
        return match.group(1).strip("\n") + "\n"
    # No COMPLETE fenced block — usually a truncated response whose closing ```
    # never arrived. Falling through with the raw text leaks the orphan opening
    # ```go line into the file ("expected 'package', found ``"). Strip a leading
    # opening fence and any trailing partial fence so a nearly-good file still
    # has a chance to compile.
    text = model_output.strip("\n")
    text = re.sub(r"^\s*```(?:go|golang|mod|yaml|markdown|md|text)?[ \t]*\n", "", text)
    text = re.sub(r"\n?```[ \t]*$", "", text)
    return text.strip("\n") + "\n"


_IMPORT_BLOCK_RE = re.compile(r"import\s*\((.*?)\)", re.DOTALL)
_IMPORT_SINGLE_RE = re.compile(r'import\s+(?:[\w.]+\s+)?"([^"]+)"')
_QUOTED_RE = re.compile(r'"([^"]+)"')


def nonstdlib_imports(code: str) -> list[str]:
    """Return the import paths in *code* that are NOT standard library.

    A stdlib import path's first segment has no dot (``fmt``, ``net/http``); a
    third-party one carries a domain (``github.com/...``, ``golang.org/x/...``).
    Used to reject best-of-N candidates that reach for an external dependency the
    Builder forbids (small coders love to import ``gorilla/mux`` for a router).
    """
    paths: list[str] = []
    for block in _IMPORT_BLOCK_RE.findall(code):
        paths.extend(_QUOTED_RE.findall(block))
    paths.extend(_IMPORT_SINGLE_RE.findall(code))
    return [p for p in paths if "." in p.split("/")[0]]


# --------------------------------------------------------------------------- #
# Coder protocol + implementations
# --------------------------------------------------------------------------- #


class Coder(Protocol):
    """A pluggable code-generating model."""

    def generate(self, prompt: str) -> str:  # pragma: no cover - protocol
        ...


class OpenAICoder:
    """Coder backed by any OpenAI-compatible chat-completions endpoint.

    Defaults target a local Ollama server serving the ``guildlm-go`` model.
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        # Imported lazily so the rest of the module (and the offline tests) do
        # not require the openai SDK to be importable at module load.
        from openai import OpenAI

        self.model = model or os.environ.get("GUILDLM_BUILDER_MODEL", "guildlm-go")
        base_url = base_url or os.environ.get(
            "GUILDLM_BUILDER_BASE_URL", "http://localhost:11434/v1"
        )
        # Ollama ignores the key but the SDK requires a non-empty string.
        api_key = api_key or os.environ.get("GUILDLM_BUILDER_API_KEY", "ollama")
        self._client = OpenAI(base_url=base_url, api_key=api_key)

    def generate(self, prompt: str) -> str:
        # A generous max_tokens is essential for LARGE files: without it the
        # server's small default (mlx_lm defaults to ~512) truncates a big file
        # like a multi-method JSON handler mid-statement, and the fix loop can
        # never recover a file that was simply cut off. Override via
        # GUILDLM_BUILDER_MAX_TOKENS.
        max_tokens = int(os.environ.get("GUILDLM_BUILDER_MAX_TOKENS", "4096"))
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert Go engineer. Output a single complete "
                        "source file. Respond with only the code inside one "
                        "fenced ```go block, no commentary."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""


class FakeCoder:
    """Deterministic Coder for tests.

    It is configured with a queue of canned responses *per file path*. Each call
    to ``generate`` matches the target file (parsed from the prompt) and returns
    the next canned response for that file, allowing a test to model "broken
    first, fixed second".
    """

    def __init__(self, responses: dict[str, list[str]]) -> None:
        # Copy so callers can reuse their dicts.
        self._responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        target = self._target_from_prompt(prompt)
        self.calls.append(target)
        queue = self._responses.get(target)
        if not queue:
            raise AssertionError(f"FakeCoder has no canned response for {target!r}")
        # Keep returning the last response once the queue is down to one, so a
        # converged file stays stable across extra fix rounds.
        return queue.pop(0) if len(queue) > 1 else queue[0]

    @staticmethod
    def _target_from_prompt(prompt: str) -> str:
        match = re.search(r"TARGET_FILE:\s*(\S+)", prompt)
        return match.group(1) if match else "?"


def role_for_path(path: str) -> str:
    """Which Go specialist owns a file: ``test`` for ``*_test.go``, else ``dev``.

    This is the routing key for the guild — implementation files go to the Go
    *development* specialist, test files to the Go *test* specialist.
    """
    return "test" if path.endswith("_test.go") else "dev"


class RoleRoutingCoder:
    """Dispatch each file to the specialist trained for its role.

    The guild working together instead of one generalist: ``_test.go`` files are
    generated/fixed by the Go *test* specialist, everything else by the Go
    *development* specialist. Each role is any ``Coder`` (typically an
    ``OpenAICoder`` pointed at a different Ollama model / adapter). Backward
    compatible — give it one role and it behaves exactly like that coder.
    """

    def __init__(self, by_role: dict[str, "Coder"], default: "Coder | None" = None) -> None:
        if not by_role:
            raise ValueError("RoleRoutingCoder needs at least one role")
        self._by_role = dict(by_role)
        self._default = default or by_role.get("dev") or next(iter(by_role.values()))

    def generate(self, prompt: str) -> str:
        match = re.search(r"TARGET_FILE:\s*(\S+)", prompt)
        role = role_for_path(match.group(1) if match else "")
        return self._by_role.get(role, self._default).generate(prompt)


# --------------------------------------------------------------------------- #
# Retrieval — ground the small model in known-good verified examples
# --------------------------------------------------------------------------- #


class Retriever:
    """Few-shot retrieval over a corpus of compile-verified Go examples.

    A small coder writes far better Go when shown a couple of similar, *known
    to compile* examples than from the instruction alone. Scoring is lexical
    Jaccard over alphanumeric tokens — no embeddings, no deps, fully offline
    ($0). Feed it the teacher dataset's go_dev split (instruction/response).
    """

    _TOK = re.compile(r"[a-z0-9]+")

    def __init__(self, examples: Sequence[tuple[str, str]]) -> None:
        self._ex = [(i, r, set(self._TOK.findall(i.lower()))) for i, r in examples]

    def top_k(self, query: str, k: int) -> list[tuple[str, str]]:
        if k <= 0:
            return []
        q = set(self._TOK.findall(query.lower()))
        if not q:
            return []
        scored = []
        for instr, resp, toks in self._ex:
            inter = len(q & toks)
            if not inter:
                continue
            scored.append((inter / len(q | toks), instr, resp))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [(i, r) for _, i, r in scored[:k]]

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "Retriever":
        examples: list[tuple[str, str]] = []
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                instr, resp = d.get("instruction") or "", d.get("response") or ""
                if instr and resp:
                    examples.append((instr, resp))
        return cls(examples)


# --------------------------------------------------------------------------- #
# Go toolchain wrapper (the compile/test feedback)
# --------------------------------------------------------------------------- #


class GoToolchain:
    """Thin wrapper around the real ``go`` CLI run in a project directory."""

    def __init__(self, go_bin: str = "go") -> None:
        self.go_bin = go_bin

    def _run(self, args: Sequence[str], cwd: str | Path) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                [self.go_bin, *args],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError:
            return False, f"go toolchain not found ({self.go_bin!r})"
        except subprocess.TimeoutExpired:
            return False, f"`go {' '.join(args)}` timed out"
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, out.strip()

    def build(self, cwd: str | Path) -> tuple[bool, str]:
        return self._run(["build", "./..."], cwd)

    def vet(self, cwd: str | Path) -> tuple[bool, str]:
        return self._run(["vet", "./..."], cwd)

    def test(self, cwd: str | Path) -> tuple[bool, str]:
        return self._run(["test", "./..."], cwd)

    def check(self, cwd: str | Path) -> tuple[bool, str]:
        """Run build, then vet, then test; stop at the first failure.

        Returns the combined output of the stage that ran. This is the feedback
        signal the agent loop fixes against.
        """
        for stage in (self.build, self.vet, self.test):
            ok, out = stage(cwd)
            if not ok:
                return False, out
        return True, "build, vet and test passed"

    def build_vet(self, cwd: str | Path) -> tuple[bool, str]:
        """Build + vet only (no test). ``go build ./...`` ignores ``_test.go``
        files, so this is the right intermediate gate when editing implementation
        before its tests have caught up — used by staged maintenance."""
        for stage in (self.build, self.vet):
            ok, out = stage(cwd)
            if not ok:
                return False, out
        return True, "build and vet passed"

    def syntax_ok(self, code: str) -> bool:
        """True if *code* is syntactically valid Go (parses cleanly).

        Uses ``gofmt`` (always shipped with the toolchain) on stdin — it exits
        non-zero on a parse error. This is a cheap, whole-project-independent
        gate for best-of-N generation: reject candidates that don't even parse
        before paying for a full build.
        """
        try:
            proc = subprocess.run(
                [self.go_bin.replace("go", "gofmt") if self.go_bin.endswith("go") else "gofmt", "-e"],
                input=code,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return True  # gofmt unavailable -> don't block generation
        return proc.returncode == 0


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #


def _retrieval_block(shots: Sequence[tuple[str, str]] | None) -> str:
    if not shots:
        return ""
    parts = [
        "Similar verified Go examples for reference (these compile; adapt the "
        "idiom to the spec, do not copy verbatim):\n"
    ]
    for instr, resp in shots:
        parts.append(f"# Example task: {instr}\n{resp}\n")
    parts.append("\n")
    return "".join(parts)


def _generate_prompt(
    spec: Spec,
    task: FileTask,
    written: dict[str, str],
    shots: Sequence[tuple[str, str]] | None = None,
) -> str:
    """Prompt for first-pass generation of one file."""
    target_dir = _dir_of(task.spec.path)
    same_pkg = {p: c for p, c in written.items() if _dir_of(p) == target_dir}
    context = _package_context(written, task.spec.path, spec.go_module)
    reuse_rule = (
        "The SAME-PACKAGE files above (same directory) are part of THIS package. "
        "Every function, type, constant and variable they declare already exists "
        "— call and reference them directly, and do NOT redeclare or reimplement "
        "any of them (a Go 'redeclared in this block' error). For test files: do "
        "not paste copies of the functions under test, just call them.\n"
        "USE SIBLING TYPES EXACTLY AS DECLARED: match struct vs interface. If a "
        "shared type is an interface, hold and pass it BY VALUE (`s Store`), "
        "never as a pointer `*Store` — a pointer-to-interface has no methods and "
        "will not compile. Call the methods that actually exist; do not invent "
        "method names.\n\n"
        if same_pkg
        else ""
    )
    # For a multi-package project, symbols in OTHER packages are reached by
    # importing that package and qualifying (pkg.Symbol) — never by redeclaring.
    other_pkg = {p for p in written if _dir_of(p) != target_dir}
    cross_pkg_rule = (
        "This project spans MULTIPLE PACKAGES (see the OTHER-PACKAGE APIs above). "
        "To use a symbol from another package, IMPORT that package by its full "
        "path (module path + '/' + its directory) and call it qualified as "
        "`pkgname.Symbol`. Only EXPORTED (capitalised) names are visible across "
        "packages. Do NOT redeclare another package's types locally. This file's "
        "own `package` clause must match its directory's package name.\n"
        "CALL OTHER-PACKAGE FUNCTIONS WITH THEIR EXACT SIGNATURE shown above — do "
        "not add or drop a parameter (e.g. do not pass a context.Context to a "
        "method that does not take one, and DO pass it to one that does), and "
        "match the return arity. When you construct a struct, the field names in "
        "the literal MUST be the struct's declared field names.\n\n"
        if other_pkg
        else ""
    )
    # Test files are where models invent edge cases whose expected value
    # contradicts the spec (e.g. asserting an emoji string is "not a palindrome"
    # when the spec says only letters/digits count, so it filters to empty ->
    # true). Anchor the test author to the spec's stated rules.
    test_rule = (
        "This is a TEST file. Derive every expected value strictly from the "
        "behaviour described above for the functions under test — do not invent "
        "edge cases whose expected result contradicts those stated rules. If you "
        "are unsure what an exotic input (emoji, combining marks, mixed scripts) "
        "should produce under the rules, omit that case rather than guess.\n"
        "ISOLATE STATE: each test case (each t.Run subtest and each table row) "
        "MUST construct its OWN fresh instance of the system under test (a new "
        "store/server/handler) — never share one mutable instance across cases, "
        "or state from an earlier case (e.g. an already-created record) makes a "
        "later case fail spuriously (a duplicate returns 409 where the case "
        "expected 201). Declare every local with := in the scope that uses it.\n"
        "HTTP-TEST HYGIENE: build a FRESH request body for every request — an "
        "io.Reader/bytes.Buffer is drained after one read, so reusing it sends an "
        "empty body on the second request (a re-POST then wrongly returns 400 "
        "instead of 409). When a case wants 'malformed JSON', send genuinely "
        "unparseable bytes like `{\"x\":` (truncated) — NOT valid-but-empty `{}`, "
        "which decodes fine and returns 201.\n"
        "NAMING: a test function is `func TestX(t *testing.T)` — NEVER declare a "
        "local variable named `t` inside it (e.g. `var t models.Task`), it "
        "shadows/redeclares the *testing.T and breaks every t.Fatalf after it. "
        "Name locals distinctly: got, want, task, rec, resp, err.\n\n"
        if task.spec.path.endswith("_test.go")
        else ""
    )
    # Registering routes with a Go 1.22+ ServeMux is a reliable small-model
    # trap: it writes the SAME bare pattern twice (List + Create both on
    # "/tasks"), which PANICS at startup ("conflicts with pattern") and fails
    # every test — a runtime panic the fix loop can't reason its way out of.
    routing_rule = (
        "ROUTING (Go 1.22+ ServeMux): register each route as METHOD + space + "
        "pattern, e.g. mux.HandleFunc(\"GET /tasks\", h.List) and "
        "mux.HandleFunc(\"POST /tasks\", h.Create). NEVER register the same bare "
        "pattern twice (two mux.HandleFunc(\"/tasks\", ...) calls) — ServeMux "
        "PANICS at startup. Read path wildcards like {id} via r.PathValue(\"id\")"
        ".\n\n"
        if (task.spec.path.endswith(".go")
            and re.search(r"ServeMux|HandleFunc|\brout(?:e|er|ing)\b",
                          task.spec.purpose, re.I))
        else ""
    )
    # Small models cut corners on repetitive code — they implement the first few
    # methods of an interface and STUB the rest (return ErrNotImplemented / panic
    # / TODO), which either references an undefined symbol or leaves the type not
    # satisfying its interface. Demand full implementations.
    completeness_rule = (
        "IMPLEMENT EVERY function and method FULLY with real working logic — do "
        "NOT stub or leave placeholders (no `return ErrNotImplemented`, no "
        "`panic(\"not implemented\")`, no TODO). If several methods are similar "
        "(e.g. the Project methods mirror the Task methods), write out each one "
        "completely. Never reference a symbol you have not defined or imported.\n\n"
        if task.spec.path.endswith(".go") and not task.spec.path.endswith("_test.go")
        else ""
    )
    return (
        f"Project: {spec.name}\n"
        f"Language: {spec.language}\n"
        f"Description: {spec.description}\n"
        f"Go module path: {spec.go_module or '(see go.mod)'}\n\n"
        f"TARGET_FILE: {task.spec.path}\n"
        f"Purpose of this file: {task.spec.purpose}\n\n"
        f"All files in this project:\n{_file_list(spec)}\n"
        f"{_retrieval_block(shots)}"
        f"{context}"
        f"{reuse_rule}"
        f"{cross_pkg_rule}"
        f"{routing_rule}"
        f"{completeness_rule}"
        f"{test_rule}"
        f"Write the complete contents of {task.spec.path}. "
        f"Use only the Go standard library. Output one fenced ```go block."
    )


def _fix_prompt(
    task: FileTask,
    current: str,
    error_output: str,
    siblings: dict[str, str] | None = None,
) -> str:
    """Prompt asking the coder to repair one file given toolchain errors.

    ``siblings`` are the project's other already-written files. Without them a
    model cannot tell that a "redeclared in this block" error means *its own*
    copy of a symbol is the duplicate to delete — it only sees the one file.
    """
    sibling_block = ""
    all_sib = {p: c for p, c in (siblings or {}).items() if p != task.spec.path}
    tdir = _dir_of(task.spec.path)
    same = {p: c for p, c in all_sib.items() if _dir_of(p) == tdir}
    other = {p: c for p, c in all_sib.items() if _dir_of(p) != tdir}
    parts: list[str] = []
    if same:
        parts.append(
            "--- other files in THIS package (they already exist; reference "
            "their symbols, do not redeclare them) ---\n"
        )
        for path, content in same.items():
            parts.append(f"--- {path} ---\n{content}\n")
    if other:
        parts.append(
            "--- OTHER-PACKAGE APIs (import by path, call qualified pkg.Symbol; "
            "only exported names are visible) ---\n"
        )
        by_dir: dict[str, list[str]] = {}
        for p, c in other.items():
            by_dir.setdefault(_dir_of(p), []).append(c)
        for d, codes in sorted(by_dir.items()):
            pkg = pkg_name_of(codes[0])
            parts.append(f"--- package {pkg} (dir {d}) ---\n")
            for c in codes:
                parts.append("\n".join(exported_api(c).splitlines()[1:]) + "\n")
    if parts:
        sibling_block = "".join(parts) + "\n"
    # A failing assertion (the code compiled but a test's want != got) is a
    # different bug from a compile error: often the implementation is correct
    # per the spec and the TEST asserted a wrong expected value. Steer the fixer
    # toward correcting the expectation instead of corrupting a correct impl.
    is_assertion_failure = _is_test_failure(error_output)
    assertion_rule = (
        "This is a FAILING TEST ASSERTION, not a compile error — the code built "
        "and ran. Decide which side is wrong against the behaviour described in "
        "the spec: if the implementation already matches the spec's stated "
        "rules, correct the test's expected value (do not change a "
        "spec-correct implementation just to satisfy a wrong expectation). "
        "Only change the implementation if it genuinely violates the spec.\n\n"
        if is_assertion_failure
        else ""
    )
    # A missing-module error means the model reached for a third-party import
    # (e.g. golang.org/x/...) the spec forbids. The fixer otherwise loops
    # forever re-adding it, so call it out explicitly and demand a stdlib swap.
    import_rule = (
        "This file imports a package that is NOT in the Go standard library, "
        "which the spec forbids — there are no external dependencies. Remove "
        "that import entirely and reimplement what you needed with the standard "
        "library only (do not run `go get`).\n\n"
        if _is_missing_module(error_output)
        else ""
    )
    return (
        f"TARGET_FILE: {task.spec.path}\n"
        f"Purpose: {task.spec.purpose}\n\n"
        f"The Go toolchain reported errors for the project. Fix this file so the "
        f"project builds, vets and tests cleanly. Keep the same package and "
        f"public API unless the error requires a change. If the error says "
        f"'redeclared in this block', a symbol defined here already exists in "
        f"one of the other files below — delete your duplicate and call the "
        f"existing one instead.\n\n"
        f"{import_rule}"
        f"{assertion_rule}"
        f"{sibling_block}"
        f"--- current {task.spec.path} ---\n{current}\n"
        f"--- toolchain output ---\n{error_output}\n\n"
        f"Output the corrected complete file as one fenced ```go block."
    )


def _is_test_failure(error_output: str) -> bool:
    """True when the output is a failing test (compiled, ran, assertion failed)
    rather than a build/vet error. Test failures show go's ``--- FAIL`` marker;
    compile errors do not.
    """
    return "--- FAIL" in error_output or "\n--- FAIL" in error_output


def _is_missing_module(error_output: str) -> bool:
    """True when the build failed because a file imports a non-stdlib package
    the module does not provide — go prints ``no required module provides
    package``. The coder loops re-adding such imports unless told to drop them.
    """
    return "no required module provides package" in error_output


def _file_list(spec: Spec) -> str:
    return "\n".join(f"  - {f.path}: {f.purpose}" for f in spec.files) + "\n\n"


def _context_block(written: dict[str, str]) -> str:
    if not written:
        return ""
    parts = ["Already-written files for context:\n"]
    for path, content in written.items():
        parts.append(f"--- {path} ---\n{content}\n")
    parts.append("\n")
    return "".join(parts)


def _package_context(
    written: dict[str, str], target_path: str, module: str | None
) -> str:
    """Package-aware context. Same-directory files (THIS package) are shown in
    FULL — the model calls them directly. Files in OTHER directories are shown
    as their imported EXPORTED api only, grouped by package with its import path,
    so the model imports and qualifies (pkg.Symbol) instead of trying to use
    them as same-package locals."""
    target_dir = _dir_of(target_path)
    same = {p: c for p, c in written.items() if _dir_of(p) == target_dir and p != target_path}
    others: dict[str, dict[str, str]] = {}
    for p, c in written.items():
        d = _dir_of(p)
        if d != target_dir:
            others.setdefault(d, {})[p] = c

    parts: list[str] = []
    if same:
        parts.append("Already-written files in THIS package (same directory):\n")
        for p, c in same.items():
            parts.append(f"--- {p} ---\n{c}\n")
        parts.append("\n")
    if others:
        parts.append(
            "OTHER-PACKAGE APIs — import these; only exported names are visible:\n"
        )
        for d, files in sorted(others.items()):
            any_code = next(iter(files.values()))
            pkg = pkg_name_of(any_code)
            imp = f"{module}/{d}" if module and d else (module or d)
            parts.append(f'--- package {pkg}  (import "{imp}") ---\n')
            for c in files.values():
                body = "\n".join(exported_api(c).splitlines()[1:])  # drop dup pkg line
                if body.strip():
                    parts.append(body + "\n")
            parts.append("\n")
    return "".join(parts)


def _offending_files(error_output: str, known: Sequence[str]) -> list[str]:
    """Best-effort: which known files does the error output reference?

    go reports errors like ``./store.go:12:3: ...``. We match basenames so a fix
    round targets only the files actually implicated; if none match we fall back
    to all files (caller's responsibility).
    """
    hits = [p for p in known if os.path.basename(p) in error_output]
    return hits


# --------------------------------------------------------------------------- #
# The core build loop
# --------------------------------------------------------------------------- #


def _log(msg: str) -> None:
    print(f"[guildlm-build] {msg}", file=sys.stderr, flush=True)


_TOPLEVEL_RE = re.compile(r"^(?:func|type|var|const)\s+(\w+)", re.MULTILINE)
_DECL_BLOCK_RE = re.compile(r"^(?:var|const)\s*\((.*?)^\)", re.MULTILINE | re.DOTALL)


def top_level_decls(code: str) -> set[str]:
    """Package-level names a Go file declares: plain funcs (not methods), types,
    vars and consts, including names inside ``var (...)`` / ``const (...)`` blocks.

    Used to detect the small-model multi-file collapse where a 7B crams the whole
    project's types into several files, redeclaring symbols across them.
    """
    names = set(_TOPLEVEL_RE.findall(code))
    for block in _DECL_BLOCK_RE.findall(code):
        for line in block.splitlines():
            m = re.match(r"\s*(\w+)", line)
            if m:
                names.add(m.group(1))
    return names


def strip_redeclarations(code: str, forbidden: set[str]) -> str:
    """Delete top-level declarations (and their doc comments) whose name a
    SIBLING file already declares — the dominant failure when a small model
    writes a larger multi-file backend: it re-defines shared sentinels/types
    (e.g. store.go re-declares errors.go's ErrNotFound), an unrecoverable
    "redeclared in this block" error the fix loop bounces on. Deterministically
    removing the duplicate (the sibling owns it, same package) is the goimports-
    style repair. Only PLAIN funcs are stripped (methods can legitimately share
    a name across types). Conservative: on any structural ambiguity it keeps the
    line."""
    if not forbidden:
        return code
    lines = code.splitlines()
    n = len(lines)
    keep = [True] * n

    def comment_start(idx: int) -> int:
        j = idx - 1
        while j >= 0 and lines[j].strip().startswith("//"):
            j -= 1
        return j + 1

    i = 0
    while i < n:
        stripped = lines[i].strip()
        m = re.match(r"^(var|const|func|type)\b(.*)", stripped)
        if not m:
            i += 1
            continue
        kw, rest = m.group(1), m.group(2)

        # var(...) / const(...) block: drop matching inner lines
        if kw in ("var", "const") and rest.lstrip().startswith("("):
            j = i + 1
            inner = []
            while j < n and lines[j].strip() != ")":
                inner.append(j)
                j += 1
            any_kept = False
            for bl in inner:
                nm = re.match(r"\s*(\w+)", lines[bl])
                if nm and nm.group(1) in forbidden:
                    keep[bl] = False
                elif lines[bl].strip():
                    any_kept = True
            if not any_kept:  # whole block became empty -> drop it entirely
                keep[i] = False
                if j < n:
                    keep[j] = False
                for k in range(comment_start(i), i):
                    keep[k] = False
            i = j + 1
            continue

        # single decl (possibly brace-delimited: func body, struct/interface type)
        if kw == "func":
            pm = re.match(r"func\s+(\w+)", stripped)  # plain func only, no receiver
            name = pm.group(1) if pm else None
        else:
            nm = re.match(r"(?:var|const|type)\s+(\w+)", stripped)
            name = nm.group(1) if nm else None
        # A func (and a block type) is brace-delimited, but with a MULTI-LINE
        # signature the opening { sits a few lines down — keep scanning to it
        # before brace-matching, or we'd delete only the signature line and
        # orphan the body. A `type X Y` alias / `var X = ...` has no brace.
        needs_body = kw == "func" or (
            kw == "type" and ("{" in lines[i] or "struct" in stripped or "interface" in stripped)
        )
        brace = lines[i].count("{") - lines[i].count("}")
        seen_open = "{" in lines[i]
        j = i
        while (brace > 0 or (needs_body and not seen_open)) and j + 1 < n:
            j += 1
            if "{" in lines[j]:
                seen_open = True
            brace += lines[j].count("{") - lines[j].count("}")
        if name and name in forbidden:
            for k in range(i, j + 1):
                keep[k] = False
            for k in range(comment_start(i), i):
                keep[k] = False
        i = j + 1

    return "\n".join(lines[k] for k in range(n) if keep[k]).strip("\n") + "\n"


_PKG_RE = re.compile(r"^package\s+(\w+)", re.MULTILINE)


def _dir_of(path: str) -> str:
    """The package unit for a file = its directory. Files that share a directory
    are the SAME Go package; different directories are different packages that
    must import one another. '' for module-root files."""
    return os.path.dirname(path)


def pkg_name_of(code: str) -> str:
    m = _PKG_RE.search(code)
    return m.group(1) if m else "main"


def exported_api(code: str) -> str:
    """The EXPORTED surface another package sees when it imports this one:
    the package clause, exported type declarations (full — callers need field
    and method shapes), and exported func/method SIGNATURES (bodies elided).
    Unexported symbols are hidden. Lets a cross-package consumer call
    ``pkg.Symbol`` correctly without carrying every body."""
    lines = code.splitlines()
    n = len(lines)
    out: list[str] = []
    i = 0
    while i < n:
        s = lines[i].strip()
        m = re.match(r"^(func|type|var|const)\b", s)
        if not m:
            i += 1
            continue
        kw = m.group(1)
        brace = lines[i].count("{") - lines[i].count("}")
        j = i
        while brace > 0 and j + 1 < n:
            j += 1
            brace += lines[j].count("{") - lines[j].count("}")
        if kw == "func":
            fm = re.match(r"func\s+(?:\([^)]*\)\s*)?(\w+)", s)
            name = fm.group(1) if fm else ""
            if name[:1].isupper():
                out.append(lines[i].split("{")[0].rstrip())  # signature only
        elif kw == "type":
            tm = re.match(r"type\s+(\w+)", s)
            if tm and tm.group(1)[:1].isupper():
                out.extend(lines[i : j + 1])  # full type (fields/methods matter)
        else:  # var / const — keep exported singles (e.g. sentinel errors)
            vm = re.match(r"(?:var|const)\s+(\w+)", s)
            if vm and vm.group(1)[:1].isupper():
                out.append(lines[i].split("=")[0].rstrip())
        i = j + 1
    return f"package {pkg_name_of(code)}\n" + "\n".join(out) + "\n"


_UNDEF_QUAL_RE = re.compile(r"([\w./-]+\.go):\d+:\d+: undefined: (\w+)\.(\w+)")
_UNDEF_BARE_RE = re.compile(r"([\w./-]+\.go):\d+:\d+: undefined: (\w+)(?!\s*\.)")


def _ensure_import(code: str, import_path: str) -> str:
    """Add ``import "import_path"`` if absent. goimports (run on write)
    canNOT resolve LOCAL module imports from isolated content, so the Builder
    must add cross-package local imports itself; an import that turns out unused
    is pruned by goimports later, so this is safe to apply eagerly."""
    if f'"{import_path}"' in code:
        return code
    lines = code.splitlines()
    for i, l in enumerate(lines):
        if l.strip().startswith("import ("):
            lines.insert(i + 1, f'\t"{import_path}"')
            return "\n".join(lines) + "\n"
    for i, l in enumerate(lines):
        m = re.match(r'import\s+("[^"]+")\s*$', l.strip())
        if m:
            lines[i : i + 1] = ["import (", f"\t{m.group(1)}",
                                f'\t"{import_path}"', ")"]
            return "\n".join(lines) + "\n"
    for i, l in enumerate(lines):
        if l.strip().startswith("package "):
            lines[i + 1 : i + 1] = ["", f'import "{import_path}"']
            return "\n".join(lines) + "\n"
    return code


def _requalify_undefined(
    written: dict[str, str], error_output: str, module: str | None = None
) -> dict[str, str]:
    """Deterministically fix cross-package qualification errors the compiler
    pinpoints, using the project's own package structure:
      * MISQUALIFIED — `undefined: wrongpkg.Sym` where Sym is exported by a
        DIFFERENT project package (handler wrote `service.ErrExists`, but
        ErrExists lives in `store`): rewrite `wrongpkg.Sym` -> `owner.Sym`.
      * UNQUALIFIED — `undefined: Sym` (bare) where Sym is exported by exactly
        one OTHER project package (test wrote `NewTaskService(...)` in package
        api instead of `service.NewTaskService`): add the `owner.` qualifier.
    goimports then adds the right import. Returns {path: new_content} for changed
    files only. Same class of mechanical repair as strip_redeclarations."""
    pkg_name_by_dir: dict[str, str] = {}
    for p, c in written.items():
        pkg_name_by_dir.setdefault(_dir_of(p), pkg_name_of(c))
    # package name -> its import path (module + dir). Skip package main / dupes.
    dir_by_pkg: dict[str, str] = {}
    for d, pname in pkg_name_by_dir.items():
        if pname != "main":
            dir_by_pkg.setdefault(pname, d)
    owners: dict[str, set[str]] = {}
    for p, c in written.items():
        pname = pkg_name_by_dir[_dir_of(p)]
        for name in top_level_decls(c):
            if name[:1].isupper():
                owners.setdefault(name, set()).add(pname)

    def import_path(pkg: str) -> str | None:
        d = dir_by_pkg.get(pkg)
        if d is None:
            return None
        return f"{module}/{d}" if module and d else (module or d)

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    changed: dict[str, str] = {}

    def apply(path: str, pattern: str, repl: str, owner: str) -> None:
        code = changed.get(path, written[path])
        new = re.sub(pattern, repl, code)
        if new != code:
            imp = import_path(owner)
            if imp:
                new = _ensure_import(new, imp)
            changed[path] = new

    # misqualified: wrongpkg.Sym -> owner.Sym (+ import owner)
    for m in _UNDEF_QUAL_RE.finditer(error_output):
        path = resolve(m.group(1))
        wrongpkg, sym = m.group(2), m.group(3)
        if not path:
            continue
        correct = owners.get(sym, set()) - {wrongpkg}
        if len(correct) == 1:
            owner = next(iter(correct))
            apply(path, rf"\b{re.escape(wrongpkg)}\.{re.escape(sym)}\b",
                  f"{owner}.{sym}", owner)
    # bare Sym: either a missing local PACKAGE import, or an unqualified symbol
    for m in _UNDEF_BARE_RE.finditer(error_output):
        path = resolve(m.group(1))
        name = m.group(2)
        if not path:
            continue
        own_pkg = pkg_name_by_dir.get(_dir_of(path))
        if name in dir_by_pkg and name != own_pkg:
            # `undefined: models` — a local package used qualified but not imported
            imp = import_path(name)
            code = changed.get(path, written[path])
            if imp and f'"{imp}"' not in code:
                changed[path] = _ensure_import(code, imp)
        else:
            correct = owners.get(name, set()) - {own_pkg}
            if len(correct) == 1:
                owner = next(iter(correct))
                apply(path, rf"(?<![\w.]){re.escape(name)}\b(?=\s*\()",
                      f"{owner}.{name}", owner)
    return changed


_ARITY_RE = re.compile(
    r"([\w./-]+\.go):(\d+):\d+: assignment mismatch: "
    r"(\d+) variables? but [\w.()\[\]*]+ returns (\d+) values?"
)


def _fix_assignment_arity(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """Deterministically fix ``assignment mismatch: N variables but f returns M
    values`` at the compiler-pinpointed line: with too many variables, drop
    blank ``_`` identifiers (rightmost first) until the counts match; with too
    few, pad the LHS with ``_``. Only blanks are ever added or removed — named
    variables are never touched, so a genuinely wrong call is left for the
    model. Returns {path: new_content} for changed files only."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    for m in _ARITY_RE.finditer(error_output):
        path = resolve(m.group(1))
        if not path:
            continue
        lineno, nvars, nvals = int(m.group(2)), int(m.group(3)), int(m.group(4))
        if nvals == 0:
            continue  # right fix is deleting the assignment — model's call
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        line = lines[lineno - 1]
        sep = ":=" if ":=" in line else None
        if sep is None:
            em = re.search(r"(?<![=!<>+\-*/%&|^])=(?!=)", line)
            if not em:
                continue
            sep = "="
        lhs, rhs = line.split(sep, 1)
        names = [n.strip() for n in lhs.split(",")]
        if len(names) != nvars or not all(
            re.fullmatch(r"[\w.\[\]*]+", n.split()[-1]) for n in names if n
        ):
            continue
        if nvars > nvals:
            for i in range(len(names) - 1, -1, -1):
                if len(names) == nvals:
                    break
                if names[i] == "_":
                    names.pop(i)
            if len(names) != nvals:
                continue  # extra vars are named, not ours to drop
        else:
            names += ["_"] * (nvals - nvars)
        indent = lhs[: len(lhs) - len(lhs.lstrip())]
        if sep == ":=" and all(n == "_" for n in names):
            sep = "="  # `_, _ :=` declares nothing — invalid Go
        lines[lineno - 1] = f"{indent}{', '.join(names)} {sep}{rhs}"
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
    return changed


_ASSERTION_RE = re.compile(r"\bt\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\b")


def has_assertions(code: str) -> bool:
    """True if a Go test file contains at least one failing assertion. A test
    with no ``t.Error``/``t.Fatal``/… can pass trivially without testing
    anything, so we reject such candidates during best-of-N for *_test.go files."""
    return bool(_ASSERTION_RE.search(code))


def _is_clean(
    code: str,
    is_go: bool,
    toolchain: GoToolchain,
    sibling_decls: set[str] | None = None,
    require_assertions: bool = False,
) -> bool:
    """A clean Go candidate parses, imports only the standard library, does not
    redeclare a sibling's package-level symbol, and — for test files — actually
    asserts something."""
    if not is_go:
        return True
    if not toolchain.syntax_ok(code) or nonstdlib_imports(code):
        return False
    if sibling_decls and (top_level_decls(code) & sibling_decls):
        return False
    if require_assertions and not has_assertions(code):
        return False
    return True


def _sample_clean(
    coder: Coder,
    prompt: str,
    is_go: bool,
    candidates: int,
    toolchain: GoToolchain,
    what: str,
    sibling_decls: set[str] | None = None,
    require_assertions: bool = False,
) -> str:
    """Draw up to ``candidates`` samples; keep the first clean one (parses,
    stdlib-only, no cross-file redeclaration, and — for test files — actually
    asserts something). Used for BOTH generation and fixes, so a stubborn small
    model that re-adds a forbidden import (gorilla/mux), crams a sibling's types
    into this file, or writes a trivially-passing test gets resampled instead of
    poisoning the build. Falls back to the last sample so progress never stalls.
    """
    last = ""
    for attempt in range(max(1, candidates)):
        last = extract_code(coder.generate(prompt))
        if is_go and sibling_decls:
            # Deterministically drop any declaration a sibling already owns
            # (the redeclared-sentinel/type collapse) — the dead import it
            # leaves behind is pruned by goimports on write.
            stripped = strip_redeclarations(last, sibling_decls)
            if stripped != last:
                _log(f"    stripped redeclared symbols from {what} candidate")
                last = stripped
        if _is_clean(last, is_go, toolchain, sibling_decls, require_assertions):
            if attempt:
                _log(f"    best-of-N {what}: kept candidate {attempt + 1}")
            return last
    if candidates > 1:
        _log(f"    best-of-N {what}: no clean candidate; using last of {candidates}")
    return last


def _sample_verified_fix(
    coder: Coder,
    prompt: str,
    path: str,
    out: Path,
    written: dict[str, str],
    candidates: int,
    toolchain: GoToolchain,
    sibling_decls: set[str] | None = None,
    is_test: bool = False,
) -> str:
    """Fix-loop best-of-N with a GROUND-TRUTH gate: sample up to ``candidates``
    repairs, write each in place, and keep the first that makes the *whole
    project* build, vet and test cleanly. Falls back to the best parse-clean
    candidate (then the last sample) so a round always makes progress.

    This is verification-driven *selection* — the very ``go`` feedback the loop
    already trusts, applied at candidate-pick time rather than only after. A
    stubborn small model that keeps re-emitting the same wrong test expectation
    (it can't see why `want` is wrong) gets out-voted by the one sampled
    candidate that actually goes green, instead of the loop keeping whichever
    parses. Most decisive when a single file is the culprit — exactly when the
    parse-only gate is blindest.
    """
    is_go = path.endswith(".go")
    best_clean: str | None = None
    last = written.get(path, "")
    for attempt in range(max(1, candidates)):
        cand = extract_code(coder.generate(prompt))
        if is_go and sibling_decls:
            cand = strip_redeclarations(cand, sibling_decls)
        last = cand
        if not _is_clean(cand, is_go, toolchain, sibling_decls, is_test):
            continue
        if best_clean is None:
            best_clean = cand
        _write_file(out, path, cand)
        written[path] = cand
        ok, _ = toolchain.check(out)
        if ok:
            if attempt:
                _log(f"    verified fix: candidate {attempt + 1} turns the project green")
            return cand
    chosen = best_clean if best_clean is not None else last
    _write_file(out, path, chosen)
    written[path] = chosen
    return chosen


def _generate_file(
    coder: Coder,
    spec: Spec,
    task: FileTask,
    written: dict[str, str],
    candidates: int,
    toolchain: GoToolchain,
    retriever: "Retriever | None" = None,
    shots: int = 0,
) -> str:
    """Generate one file, best-of-N: sample up to ``candidates`` times and keep
    the first that is syntactically valid Go.

    This is the small-model leverage: a 7-14B coder misfires more often than a
    32B, but a cheap ground-truth gate (does it parse?) lets us draw a few
    samples and keep a good one — turning model variance into a quality lift
    instead of a failed build. Non-Go files (go.mod) skip the gate. Falls back
    to the last sample if none parse, so generation always produces something.

    When a ``retriever`` is given, the top-``shots`` similar verified examples
    are shown to ground the model in known-good idiomatic Go.
    """
    examples = (
        retriever.top_k(f"{task.spec.path} {task.spec.purpose}", shots)
        if retriever and shots and task.spec.path.endswith(".go")
        else None
    )
    prompt = _generate_prompt(spec, task, written, shots=examples)
    is_go = task.spec.path.endswith(".go")
    # Symbols already declared by SAME-PACKAGE (same-directory) files — reject a
    # candidate that redeclares any of them (the multi-file collapse). Scoped by
    # directory so a legitimate same-named symbol in ANOTHER package is not
    # treated as a redeclaration (Go allows store.Config and config.Config).
    target_dir = _dir_of(task.spec.path)
    sibling_decls: set[str] = set()
    for p, content in written.items():
        if p != task.spec.path and _dir_of(p) == target_dir:
            sibling_decls |= top_level_decls(content)
    is_test = task.spec.path.endswith("_test.go")
    return _sample_clean(
        coder, prompt, is_go, candidates, toolchain, "gen", sibling_decls, is_test
    )


def _fix_loop(
    tasks: Sequence[FileTask],
    written: dict[str, str],
    out: Path,
    toolchain: GoToolchain,
    coder: Coder,
    max_fix_rounds: int,
    candidates: int,
    check=None,
    module: str | None = None,
) -> bool:
    """Shared ground-truth repair loop: run ``check`` (default build/vet/test),
    route each failure to the owning file, repair, re-check — up to
    ``max_fix_rounds``. Mutates ``written`` and the files under ``out``. Returns
    True iff ``check`` passes.

    ``check`` lets a caller gate on a weaker signal — e.g. staged maintenance
    converges the implementation on ``build_vet`` (no tests) before bringing the
    tests back. Used by ``build`` (generate-then-fix) and ``maintain``
    (edit-then-fix) so one verification-driven convergence backs both.
    """
    check = check or toolchain.check
    ok, output = check(out)
    if ok:
        _log("compile/test passed")
        return True
    for rnd in range(1, max_fix_rounds + 1):
        _log(f"compile/test FAILED, fix round {rnd}/{max_fix_rounds}")
        # Deterministic pre-pass: fix cross-package misqualified symbols
        # (`undefined: wrongpkg.Sym`) and blank-fixable assignment-arity
        # mismatches before spending a model round on them.
        requal = _requalify_undefined(written, output, module)
        arity = _fix_assignment_arity({**written, **requal}, output)
        requal.update(arity)
        if requal:
            for path, content in requal.items():
                _log(f"  requalified cross-package symbols in {path}")
                _write_file(out, path, content)
                written[path] = content
            ok, output = check(out)
            if ok:
                _log(f"converged to green after fix round {rnd} (deterministic)")
                return True
        targets = _offending_files(output, list(written)) or list(written)
        # Don't let the model re-fix (and re-break) a file we JUST repaired
        # deterministically this round — the qualification fix is authoritative
        # and must stick. A residual non-qualification bug in it surfaces next
        # round, when requalify is idempotent and leaves it to the model.
        if requal:
            targets = [t for t in targets if t not in requal] or targets
        for path in targets:
            task = _task_for(tasks, path)
            if task is None:
                continue
            _log(f"  fixing {path}")
            fix_prompt = _fix_prompt(task, written[path], output, written)
            fix_dir = _dir_of(path)
            sibling_decls: set[str] = set()
            for other, content in written.items():
                if other != path and _dir_of(other) == fix_dir:
                    sibling_decls |= top_level_decls(content)
            if candidates > 1:
                code = _sample_verified_fix(
                    coder, fix_prompt, path, out, written, candidates, toolchain,
                    sibling_decls, path.endswith("_test.go"),
                )
            else:
                code = _sample_clean(
                    coder, fix_prompt, path.endswith(".go"), candidates, toolchain,
                    "fix", sibling_decls, path.endswith("_test.go"),
                )
                _write_file(out, path, code)
                written[path] = code
        ok, output = check(out)
        if ok:
            _log(f"converged to green after fix round {rnd}")
            return True
    _log(f"exhausted {max_fix_rounds} fix rounds, still failing")
    return False


def build(
    spec: Spec,
    coder: Coder,
    out_dir: str | Path,
    max_fix_rounds: int = 4,
    toolchain: GoToolchain | None = None,
    candidates: int = 1,
    reviewer: "Coder | None" = None,
    review_rounds: int = 1,
    retriever: "Retriever | None" = None,
    shots: int = 0,
) -> tuple[bool, dict[str, str]]:
    """Run the agentic build loop.

    plan -> generate each file (best-of-N) -> compile/vet/test -> feed errors
    back -> fix -> re-check, up to ``max_fix_rounds`` times. When the project is
    green and a ``reviewer`` is given, a non-regressing review pass then hunts
    for semantic bugs that survive a green build.

    ``candidates`` > 1 enables rejection sampling per file (keep the first that
    parses) — the cheapest way to make a small coder behave like a bigger one.

    Returns ``(ok, files)`` where ``files`` maps path -> final content.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    toolchain = toolchain or GoToolchain()

    tasks = plan(spec)
    written: dict[str, str] = {}

    def _finish_green() -> tuple[bool, dict[str, str]]:
        if reviewer is not None and review_rounds > 0:
            _log("review pass (catch bugs that survive a green build)")
            _review_pass(spec, tasks, written, out, toolchain, reviewer, review_rounds)
        return True, written

    # --- Generation pass ---------------------------------------------------- #
    for task in tasks:
        _log(f"generate {task.spec.path} ({task.index + 1}/{len(tasks)})")
        code = _generate_file(
            coder, spec, task, written, candidates, toolchain, retriever, shots
        )
        _write_file(out, task.spec.path, code)
        written[task.spec.path] = code

    # --- Fix loop ----------------------------------------------------------- #
    if _fix_loop(tasks, written, out, toolchain, coder, max_fix_rounds, candidates,
                 module=spec.go_module):
        return _finish_green()
    return False, written


# --------------------------------------------------------------------------- #
# Maintain — edit/refactor an EXISTING project against a change request.
# This is the "maintain large projects" half of the guild: read a whole project,
# apply a change, and converge back to green with the same verification loop that
# backs generation. Strictly non-regressing by default — a change that can't stay
# green is rolled back, so maintenance never leaves the project worse than it was.
# --------------------------------------------------------------------------- #

def _load_project(project_dir: str | Path) -> dict[str, str]:
    """Read a Go project's source into {relative_path: content} (*.go + go.mod)."""
    base = Path(project_dir)
    files: dict[str, str] = {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and (p.suffix == ".go" or p.name == "go.mod"):
            files[str(p.relative_to(base))] = p.read_text(encoding="utf-8")
    return files


def _project_listing(files: dict[str, str]) -> str:
    return "".join(f"--- {p} ---\n{c}\n" for p, c in files.items())


def _maintain_plan_prompt(request: str, files: dict[str, str]) -> str:
    return (
        f"You are maintaining an existing Go project. A change is requested.\n\n"
        f"CHANGE REQUEST: {request}\n\n"
        f"Existing files:\n{_project_listing(files)}\n"
        f"List ONLY the file paths you must create or modify to satisfy the "
        f"request — one path per line, no commentary, no code. Use an existing "
        f"path to modify that file, or a new path to add one."
    )


def _parse_plan(text: str, known: set[str]) -> list[str]:
    """Extract file paths from a plan response, leniently. Falls back to the
    known non-test .go files if nothing parses."""
    out: list[str] = []
    for line in text.splitlines():
        m = re.search(r"[\w./-]+\.go\b|(?:^|[\s/])go\.mod\b", line)
        if m:
            p = m.group(0).strip().lstrip("/")
            if p and p not in out:
                out.append(p)
    if not out:
        out = [p for p in known if p.endswith(".go") and not p.endswith("_test.go")]
    return out


def _maintain_file_prompt(request: str, path: str, files: dict[str, str], is_new: bool) -> str:
    verb = "Create" if is_new else "Update"
    return (
        f"TARGET_FILE: {path}\n"
        f"You are maintaining an existing Go project. Apply this change:\n\n"
        f"CHANGE REQUEST: {request}\n\n"
        f"All current files:\n{_project_listing(files)}\n"
        f"{verb} the file `{path}` to satisfy the request. Keep the rest of the "
        f"project working: do not break callers, do not redeclare symbols that "
        f"already exist in sibling files, standard library only. Output the "
        f"COMPLETE new content of `{path}` as one fenced "
        f"{'```mod' if path.endswith('.mod') else '```go'} block."
    )


def maintain(
    project_dir: str | Path,
    request: str,
    coder: Coder,
    max_fix_rounds: int = 4,
    toolchain: GoToolchain | None = None,
    candidates: int = 1,
    reviewer: "Coder | None" = None,
    review_rounds: int = 1,
    non_regressing: bool = True,
) -> tuple[bool, dict[str, str]]:
    """Apply ``request`` to the existing Go project at ``project_dir``.

    plan (which files to touch) -> edit each with full-project context ->
    verification/repair loop -> optional review. With ``non_regressing`` (default)
    a change that fails to reach green is rolled back to the original sources.

    Returns ``(ok, files)`` with the final on-disk content.
    """
    out = Path(project_dir)
    toolchain = toolchain or GoToolchain()
    current = _load_project(out)
    if not current:
        raise ValueError(f"no Go project (*.go/go.mod) found in {project_dir}")
    original = dict(current)
    _log(f"maintain: {len(current)} files; change: {request}")

    # 1. plan which files to touch
    targets = _parse_plan(coder.generate(_maintain_plan_prompt(request, current)), set(current))
    _log(f"maintain plan -> {targets}")

    # 2-3. STAGED edit: implementation first (get it building — `go build` ignores
    # _test.go), then bring the tests up to the new implementation. Editing impl
    # and tests in one shot makes the fix loop juggle an inconsistent API on both
    # sides at once; staging gives it a compiling implementation to write tests
    # against, which is how a human maintains code too.
    def _edit(path: str) -> None:
        is_new = path not in current
        _log(f"  {'create' if is_new else 'edit'} {path}")
        sib: set[str] = set()
        for other, content in current.items():
            if other != path:
                sib |= top_level_decls(content)
        code = _sample_clean(
            coder, _maintain_file_prompt(request, path, current, is_new),
            path.endswith(".go"), candidates, toolchain, "edit", sib, path.endswith("_test.go"),
        )
        _write_file(out, path, code)
        current[path] = code

    def _tasks() -> list[FileTask]:
        return [
            FileTask(index=i, spec=FileSpec(path=p, purpose=f"maintained for change: {request}"))
            for i, p in enumerate(current)
        ]

    impl_targets = [p for p in targets if not p.endswith("_test.go")]
    test_targets = [p for p in targets if p.endswith("_test.go")]

    for path in impl_targets:
        _edit(path)
    if impl_targets:
        _log("staged maintain: converging the implementation (build+vet) before tests")
        _fix_loop(_tasks(), current, out, toolchain, coder, max_fix_rounds, candidates,
                  check=toolchain.build_vet)
    for path in test_targets:
        _edit(path)

    # 4. full verify (build+vet+test) + repair to green
    tasks = _tasks()
    if _fix_loop(tasks, current, out, toolchain, coder, max_fix_rounds, candidates):
        if reviewer is not None and review_rounds > 0:
            spec = Spec(
                name=out.name, description=f"maintained: {request}",
                files=tuple(t.spec for t in tasks),
            )
            _log("review pass on the maintained project")
            _review_pass(spec, tasks, current, out, toolchain, reviewer, review_rounds)
        return True, current

    # 4. non-regressing rollback
    if non_regressing:
        _log("maintain could not stay green — rolling back to the original sources")
        for p in list(current):
            if p not in original:
                (out / p).unlink(missing_ok=True)
        for p, c in original.items():
            _write_file(out, p, c)
        return False, original
    return False, current


def _pkg_of(files: dict[str, str]) -> str:
    """The package name declared by the project's Go files (default 'main')."""
    for content in files.values():
        m = re.search(r"^package\s+(\w+)", content, re.MULTILINE)
        if m:
            return m.group(1)
    return "main"


def write_tests(
    project_dir: str | Path,
    coder: Coder,
    toolchain: GoToolchain | None = None,
    candidates: int = 1,
    max_fix_rounds: int = 4,
    test_filename: str = "guild_test.go",
) -> tuple[bool, str]:
    """Write tests for an EXISTING project — the 'test large projects' capability.

    Generate a ``_test.go`` for the package with the whole project as context,
    then converge it to green with the same verification/repair loop that backs
    generation — so a test that doesn't compile or asserts a wrong expectation is
    repaired rather than discarded. Returns ``(ok, test_content)``.
    """
    out = Path(project_dir)
    toolchain = toolchain or GoToolchain()
    current = _load_project(out)
    impl = {p: c for p, c in current.items() if not (p.endswith("_test.go"))}
    if not any(p.endswith(".go") for p in impl):
        raise ValueError(f"no Go implementation files in {project_dir}")
    pkg = _pkg_of(impl)
    sibling_decls: set[str] = set()
    for p, c in impl.items():
        if p.endswith(".go"):
            sibling_decls |= top_level_decls(c)
    prompt = (
        f"TARGET_FILE: {test_filename}\n"
        f"Write a thorough, table-driven Go test in package {pkg} for this existing "
        f"project. Exercise the exported behaviour and edge cases with REAL "
        f"t.Error/t.Fatal assertions. Standard library only; do not redeclare any "
        f"symbol that already exists in the project.\n\n{_project_listing(impl)}\n"
        f"Output one complete {test_filename} as a single ```go block."
    )
    code = _sample_clean(
        coder, prompt, True, candidates, toolchain, "test", sibling_decls, True
    )
    _write_file(out, test_filename, code)
    current[test_filename] = code
    tasks = [
        FileTask(index=i, spec=FileSpec(path=p, purpose="tests for an existing project"))
        for i, p in enumerate(current)
    ]
    ok = _fix_loop(tasks, current, out, toolchain, coder, max_fix_rounds, candidates)
    return ok, current.get(test_filename, code)


_REVIEW_CLEAN = "CLEAN"


def _review_prompt(spec: Spec, task: FileTask, current: str, siblings: dict[str, str]) -> str:
    """Ask the review specialist to find a real bug compile+test can miss."""
    others = {p: c for p, c in siblings.items() if p != task.spec.path}
    sib = "".join(f"--- {p} ---\n{c}\n" for p, c in others.items())
    return (
        f"Project: {spec.name}\nDescription: {spec.description}\n\n"
        f"Review this Go file for a REAL correctness bug that compiles and passes "
        f"tests but is still wrong against the spec — off-by-one, wrong initial "
        f"value, boundary/overflow, wrong status code, ignored error, race. "
        f"Judge against the spec above and the sibling files, not style.\n\n"
        f"If and only if you find a real bug, output the corrected COMPLETE file "
        f"as one fenced ```go block. If the file is correct, output exactly the "
        f"single word {_REVIEW_CLEAN} and nothing else.\n\n"
        f"TARGET_FILE: {task.spec.path}\nPurpose: {task.spec.purpose}\n\n"
        f"{sib}--- {task.spec.path} ---\n{current}\n"
    )


def _review_pass(
    spec: Spec,
    tasks: Sequence[FileTask],
    written: dict[str, str],
    out: Path,
    toolchain: GoToolchain,
    reviewer: "Coder",
    rounds: int,
) -> None:
    """Let the review specialist catch semantic bugs that survive a green build.

    Strictly non-regressing: a proposed edit is applied only if the whole project
    still builds, vets and tests green afterward — review can help, never hurt.
    """
    for rnd in range(1, rounds + 1):
        changed = False
        for task in tasks:
            path = task.spec.path
            if not path.endswith(".go") or path.endswith("_test.go"):
                continue  # review implementation files only
            raw = reviewer.generate(_review_prompt(spec, task, written[path], written))
            if _REVIEW_CLEAN in raw and "```" not in raw:
                continue
            candidate = extract_code(raw)
            if candidate.strip() == written[path].strip():
                continue
            prev = written[path]
            _write_file(out, path, candidate)
            ok, _ = toolchain.check(out)
            if ok:
                _log(f"  review fixed {path}")
                written[path] = candidate
                changed = True
            else:  # regression — revert, keep the known-green version
                _write_file(out, path, prev)
        if not changed:
            _log(f"review pass {rnd}: no further changes")
            return


def _task_for(tasks: Sequence[FileTask], path: str) -> FileTask | None:
    for t in tasks:
        if t.spec.path == path:
            return t
    return None


def _goimports_bin() -> str | None:
    """Resolve a ``goimports`` binary: PATH first, then $GOPATH/bin and $GOROOT/bin
    (where ``go install golang.org/x/tools/cmd/goimports`` puts it but which may not
    be on PATH). Returns None if unavailable."""
    found = shutil.which("goimports")
    if found:
        return found
    for var in ("GOPATH", "GOROOT"):
        try:
            root = subprocess.run(
                ["go", "env", var], capture_output=True, text=True, timeout=10
            ).stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if root:
            cand = os.path.join(root, "bin", "goimports")
            if os.path.exists(cand):
                return cand
    return None


def gofmt_code(code: str) -> str:
    """Canonicalise Go source. Prefer ``goimports`` — it formats like gofmt AND
    deterministically removes unused imports / adds missing ones, which fixes the
    single most common small-model failure (a dead ``import`` that blocks compile)
    without burning a model fix-round. Falls back to ``gofmt`` when goimports is
    absent, and returns the input unchanged if neither can parse it (so a
    syntactically-broken candidate still gets written for the fix loop to repair).
    """
    tool = _goimports_bin() or "gofmt"
    try:
        proc = subprocess.run(
            [tool], input=code, capture_output=True, text=True, timeout=20
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return code
    return proc.stdout if proc.returncode == 0 and proc.stdout else code


def _write_file(out: Path, rel_path: str, content: str) -> None:
    if rel_path.endswith(".go"):
        content = gofmt_code(content)
    dest = out / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

try:
    import typer

    app = typer.Typer(
        add_completion=False,
        help="GuildLM Builder — agentic Go project generator.",
    )

    @app.command()
    def main(
        spec: str = typer.Option(..., "--spec", help="Path to the spec YAML."),
        out: str = typer.Option("./generated", "--out", help="Output directory."),
        model: str = typer.Option(
            None, "--model", help="Coder model (default env/guildlm-go)."
        ),
        base_url: str = typer.Option(
            None, "--base-url", help="OpenAI-compatible base URL."
        ),
        max_fix_rounds: int = typer.Option(
            4, "--max-fix-rounds", help="Max compile/fix iterations."
        ),
        candidates: int = typer.Option(
            1, "--candidates", help="Best-of-N per file: sample N, keep the first that parses."
        ),
        test_model: str = typer.Option(
            None, "--test-model", help="Route *_test.go files to this (Go test) specialist model."
        ),
        test_base_url: str = typer.Option(
            None, "--test-base-url", help="Base URL for --test-model (defaults to --base-url)."
        ),
        review_model: str = typer.Option(
            None, "--review-model", help="Run a non-regressing review pass with this (Go review) specialist."
        ),
        review_base_url: str = typer.Option(
            None, "--review-base-url", help="Base URL for --review-model (defaults to --base-url)."
        ),
        examples: str = typer.Option(
            None, "--examples", help="JSONL of verified examples for retrieval few-shot."
        ),
        shots: int = typer.Option(
            2, "--shots", help="How many retrieved examples to show (needs --examples)."
        ),
    ) -> None:
        """Generate a project from SPEC into OUT using a pluggable coder model."""
        spec_obj = Spec.from_yaml(spec)
        dev_coder = OpenAICoder(model=model, base_url=base_url)
        if test_model:
            # The guild splits work: dev specialist writes impl, test specialist
            # writes the tests.
            test_coder = OpenAICoder(model=test_model, base_url=test_base_url or base_url)
            coder: Coder = RoleRoutingCoder({"dev": dev_coder, "test": test_coder})
        else:
            coder = dev_coder
        reviewer = (
            OpenAICoder(model=review_model, base_url=review_base_url or base_url)
            if review_model
            else None
        )
        retriever = Retriever.from_jsonl(examples) if examples else None
        ok, _ = build(
            spec_obj, coder, out, max_fix_rounds=max_fix_rounds,
            candidates=candidates, reviewer=reviewer,
            retriever=retriever, shots=shots if examples else 0,
        )
        if not ok:
            raise typer.Exit(code=1)
        typer.echo(f"Generated {spec_obj.name} into {out}")

    @app.command()
    def maintain_cmd(
        project: str = typer.Option(..., "--project", help="Path to the existing Go project dir."),
        request: str = typer.Option(..., "--request", help="The change to apply (natural language)."),
        model: str = typer.Option(None, "--model", help="Coder model (default env/guildlm-go)."),
        base_url: str = typer.Option(None, "--base-url", help="OpenAI-compatible base URL."),
        max_fix_rounds: int = typer.Option(4, "--max-fix-rounds", help="Max compile/fix iterations."),
        candidates: int = typer.Option(1, "--candidates", help="Best-of-N per edited file."),
        review_model: str = typer.Option(None, "--review-model", help="Non-regressing review pass model."),
        review_base_url: str = typer.Option(None, "--review-base-url", help="Base URL for --review-model."),
        allow_regress: bool = typer.Option(False, "--allow-regress", help="Keep a non-green result instead of rolling back."),
    ) -> None:
        """Apply a change REQUEST to an existing PROJECT, staying green (maintain)."""
        coder = OpenAICoder(model=model, base_url=base_url)
        reviewer = (
            OpenAICoder(model=review_model, base_url=review_base_url or base_url)
            if review_model
            else None
        )
        ok, _ = maintain(
            project, request, coder, max_fix_rounds=max_fix_rounds,
            candidates=candidates, reviewer=reviewer, non_regressing=not allow_regress,
        )
        if not ok:
            typer.echo("maintain: could not converge to green" + ("" if allow_regress else " — rolled back"))
            raise typer.Exit(code=1)
        typer.echo(f"Maintained {project}: {request}")

except ImportError:  # pragma: no cover - typer optional at import time
    app = None  # type: ignore[assignment]


if __name__ == "__main__":  # pragma: no cover
    if app is None:
        sys.exit("typer is required to run the CLI: pip install typer")
    app()
