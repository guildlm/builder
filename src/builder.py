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


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #


def _generate_prompt(spec: Spec, task: FileTask, written: dict[str, str]) -> str:
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


def build(
    spec: Spec,
    coder: Coder,
    out_dir: str | Path,
    max_fix_rounds: int = 4,
    toolchain: GoToolchain | None = None,
) -> tuple[bool, dict[str, str]]:
    """Run the agentic build loop.

    plan -> generate each file -> compile/vet/test -> feed errors back -> fix ->
    re-check, up to ``max_fix_rounds`` times.

    Returns ``(ok, files)`` where ``files`` maps path -> final content.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    toolchain = toolchain or GoToolchain()

    tasks = plan(spec)
    written: dict[str, str] = {}

    # --- Generation pass ---------------------------------------------------- #
    for task in tasks:
        _log(f"generate {task.spec.path} ({task.index + 1}/{len(tasks)})")
        raw = coder.generate(_generate_prompt(spec, task, written))
        code = extract_code(raw)
        _write_file(out, task.spec.path, code)
        written[task.spec.path] = code

    # --- Fix loop ----------------------------------------------------------- #
    ok, output = toolchain.check(out)
    if ok:
        _log("compile/test passed on first try")
        return True, written

    for rnd in range(1, max_fix_rounds + 1):
        _log(f"compile/test FAILED, fix round {rnd}/{max_fix_rounds}")
        targets = _offending_files(output, list(written)) or list(written)
        for path in targets:
            task = _task_for(tasks, path)
            if task is None:
                continue
            _log(f"  fixing {path}")
            raw = coder.generate(_fix_prompt(task, written[path], output, written))
            code = extract_code(raw)
            _write_file(out, path, code)
            written[path] = code

        ok, output = toolchain.check(out)
        if ok:
            _log(f"converged to green after fix round {rnd}")
            return True, written

    _log(f"exhausted {max_fix_rounds} fix rounds, still failing")
    return False, written


def _task_for(tasks: Sequence[FileTask], path: str) -> FileTask | None:
    for t in tasks:
        if t.spec.path == path:
            return t
    return None


def _write_file(out: Path, rel_path: str, content: str) -> None:
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
    ) -> None:
        """Generate a project from SPEC into OUT using a pluggable coder model."""
        spec_obj = Spec.from_yaml(spec)
        coder = OpenAICoder(model=model, base_url=base_url)
        ok, _ = build(spec_obj, coder, out, max_fix_rounds=max_fix_rounds)
        if not ok:
            raise typer.Exit(code=1)
        typer.echo(f"Generated {spec_obj.name} into {out}")

except ImportError:  # pragma: no cover - typer optional at import time
    app = None  # type: ignore[assignment]


if __name__ == "__main__":  # pragma: no cover
    if app is None:
        sys.exit("typer is required to run the CLI: pip install typer")
    app()
