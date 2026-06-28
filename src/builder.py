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
    return model_output.strip("\n") + "\n"


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
    context = _context_block(written)
    reuse_rule = (
        "The already-written files above are part of THIS SAME package. Every "
        "function, type, constant and variable they declare already exists — "
        "call and reference them directly. Do NOT redeclare or reimplement any "
        "symbol that is already defined in those files (doing so is a Go "
        "'redeclared in this block' compile error). This matters most for test "
        "files: do not paste copies of the functions under test, just call "
        "them.\n\n"
        if written
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
        "should produce under the rules, omit that case rather than guess.\n\n"
        if task.spec.path.endswith("_test.go")
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
    others = {p: c for p, c in (siblings or {}).items() if p != task.spec.path}
    if others:
        parts = [
            "--- other files in this package (they already exist; reference "
            "their symbols, do not redeclare them) ---\n"
        ]
        for path, content in others.items():
            parts.append(f"--- {path} ---\n{content}\n")
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


def _is_clean(
    code: str, is_go: bool, toolchain: GoToolchain, sibling_decls: set[str] | None = None
) -> bool:
    """A clean Go candidate parses, imports only the standard library, and does
    not redeclare a package-level symbol that already lives in a sibling file."""
    if not is_go:
        return True
    if not toolchain.syntax_ok(code) or nonstdlib_imports(code):
        return False
    if sibling_decls and (top_level_decls(code) & sibling_decls):
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
) -> str:
    """Draw up to ``candidates`` samples; keep the first clean one (parses,
    stdlib-only, no cross-file redeclaration). Used for BOTH generation and
    fixes, so a stubborn small model that re-adds a forbidden import (gorilla/mux)
    or crams a sibling's types into this file gets resampled instead of poisoning
    the build. Falls back to the last sample so progress never stalls.
    """
    last = ""
    for attempt in range(max(1, candidates)):
        last = extract_code(coder.generate(prompt))
        if _is_clean(last, is_go, toolchain, sibling_decls):
            if attempt:
                _log(f"    best-of-N {what}: kept candidate {attempt + 1}")
            return last
    if candidates > 1:
        _log(f"    best-of-N {what}: no clean candidate; using last of {candidates}")
    return last


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
    # Symbols already declared by earlier files — reject a candidate that
    # redeclares any of them (the multi-file collapse).
    sibling_decls: set[str] = set()
    for content in written.values():
        sibling_decls |= top_level_decls(content)
    return _sample_clean(coder, prompt, is_go, candidates, toolchain, "gen", sibling_decls)


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
    ok, output = toolchain.check(out)
    if ok:
        _log("compile/test passed on first try")
        return _finish_green()

    for rnd in range(1, max_fix_rounds + 1):
        _log(f"compile/test FAILED, fix round {rnd}/{max_fix_rounds}")
        targets = _offending_files(output, list(written)) or list(written)
        for path in targets:
            task = _task_for(tasks, path)
            if task is None:
                continue
            _log(f"  fixing {path}")
            fix_prompt = _fix_prompt(task, written[path], output, written)
            sibling_decls: set[str] = set()
            for other, content in written.items():
                if other != path:
                    sibling_decls |= top_level_decls(content)
            code = _sample_clean(
                coder, fix_prompt, path.endswith(".go"), candidates, toolchain, "fix", sibling_decls
            )
            _write_file(out, path, code)
            written[path] = code

        ok, output = toolchain.check(out)
        if ok:
            _log(f"converged to green after fix round {rnd}")
            return _finish_green()

    _log(f"exhausted {max_fix_rounds} fix rounds, still failing")
    return False, written


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


def gofmt_code(code: str) -> str:
    """Format Go source with gofmt; return the input unchanged if gofmt is
    missing or can't parse it (so a syntactically-broken candidate still gets
    written for the fix loop to repair). Canonicalising every file the way a real
    Go developer would makes output idiomatic and keeps cross-file checks stable.
    """
    try:
        proc = subprocess.run(
            ["gofmt"], input=code, capture_output=True, text=True, timeout=20
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

except ImportError:  # pragma: no cover - typer optional at import time
    app = None  # type: ignore[assignment]


if __name__ == "__main__":  # pragma: no cover
    if app is None:
        sys.exit("typer is required to run the CLI: pip install typer")
    app()
