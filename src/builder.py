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


def nonstdlib_imports(code: str, module: str | None = None) -> list[str]:
    """Return the import paths in *code* that are FOREIGN — neither the standard
    library nor this project's own packages.

    A stdlib import path's first segment has no dot (``fmt``, ``net/http``); a
    third-party one carries a domain (``github.com/...``, ``golang.org/x/...``).
    Used to reject best-of-N candidates that reach for an external dependency the
    Builder forbids (small coders love to import ``gorilla/mux`` for a router).

    ``module`` is the project's own module path, and passing it is not optional in
    practice: a project's own packages (``guildlm.dev/workapi/internal/store``)
    carry a domain too, so without it EVERY file of EVERY multi-package project
    looks like it reached for a foreign dependency — and best-of-N, which uses
    this to decide whether a candidate is clean, rejects all of them and silently
    degenerates into "keep the last sample". It did exactly that, for months.
    """
    paths: list[str] = []
    for block in _IMPORT_BLOCK_RE.findall(code):
        paths.extend(_QUOTED_RE.findall(block))
    paths.extend(_IMPORT_SINGLE_RE.findall(code))
    foreign = [p for p in paths if "." in p.split("/")[0]]
    if module:
        foreign = [
            p for p in foreign
            if p != module and not p.startswith(f"{module}/")
        ]
    return foreign


# --------------------------------------------------------------------------- #
# Coder protocol + implementations
# --------------------------------------------------------------------------- #


class Coder(Protocol):
    """A pluggable code-generating model."""

    def generate(
        self, prompt: str, temperature: float | None = None
    ) -> str:  # pragma: no cover - protocol
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

    def generate(self, prompt: str, temperature: float | None = None) -> str:
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
            # Near-greedy by default (reproducible runs). For data farming this
            # makes repeat rounds of the same spec byte-identical — zero new
            # distillation pairs. Raise via GUILDLM_BUILDER_TEMP (e.g. 0.6)
            # when diversity matters more than determinism.
            #
            # DO NOT ADD `seed=` HERE HOPING TO PIN A RUN. mlx_lm 0.31.3 reads a
            # request seed (server.py:1191, `self.seed = self.body.get("seed")`)
            # and calls mx.random.seed with it (server.py:956) — and on the path
            # our requests take it changes NOTHING. Measured against the live
            # server: seeds 1 / 999 / 123456 at temperature=2.0 return
            # byte-identical completions. It is not needed either: this server is
            # already deterministic per (prompt, temperature) — three 1200-token
            # generations at temp=0.1 came back byte-identical, and three at
            # temp=2.0 returned the same garbage.
            #
            # I wrote "mlx_lm honors a per-request seed — the hole is closable"
            # in 612c4f3 after READING that code and never running it. Same law
            # as the deaf widener and the silent gates: a mechanism that exists
            # in the source is not a mechanism that fires. Test, then claim.
            #
            # The consequence matters more than the correction: since generation
            # is deterministic, run-to-run divergence CANNOT come from sampling.
            # It comes from the PROMPT — and the fix prompt is built from
            # toolchain output. That is where to look.
            #
            # It also means a caller who wants a DIFFERENT sample cannot get one
            # by asking twice; the only handle that moves the output is this
            # temperature. `_sample_clean` uses it to make best-of-N real.
            temperature=(
                float(os.environ.get("GUILDLM_BUILDER_TEMP", "0.1"))
                if temperature is None
                else temperature
            ),
            max_tokens=max_tokens,
            # mlx_lm-served Qwen instruct models carry eos_token_id=151643
            # (<|endoftext|>) in the mlx-community config, so the server never
            # stops at <|im_end|> — a tuned adapter (which no longer emits
            # <|endoftext|>) then generates garbage until max_tokens on EVERY
            # call, costing minutes per file. An explicit stop word fixes it
            # at the request layer. Override via GUILDLM_BUILDER_STOP ("" to
            # disable, comma-separated to extend).
            stop=[w for w in os.environ.get("GUILDLM_BUILDER_STOP", "<|im_end|>").split(",") if w] or None,
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

    def generate(self, prompt: str, temperature: float | None = None) -> str:
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

    def generate(self, prompt: str, temperature: float | None = None) -> str:
        match = re.search(r"TARGET_FILE:\s*(\S+)", prompt)
        role = role_for_path(match.group(1) if match else "")
        return self._by_role.get(role, self._default).generate(prompt, temperature)


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
        self._ex = [
            (i, r, set(self._TOK.findall(i.lower())), "func Test" in r)
            for i, r in examples
        ]

    def top_k(
        self, query: str, k: int, prefer_tests: bool | None = None
    ) -> list[tuple[str, str]]:
        """``prefer_tests`` ranks role-matching examples first: a *_test.go
        target learns the assertion SHAPE from test examples (an impl example
        in that slot teaches it nothing about tables/fakes), and vice versa.
        Similarity still orders examples within each role."""
        if k <= 0:
            return []
        q = set(self._TOK.findall(query.lower()))
        if not q:
            return []
        scored = []
        for instr, resp, toks, is_test in self._ex:
            inter = len(q & toks)
            if not inter:
                continue
            scored.append((inter / len(q | toks), is_test, instr, resp))
        if prefer_tests is None:
            scored.sort(key=lambda t: t[0], reverse=True)
        else:
            scored.sort(key=lambda t: (t[1] == prefer_tests, t[0]), reverse=True)
        return [(i, r) for _, _, i, r in scored[:k]]

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


def _as_text(chunk: str | bytes | None) -> str:
    """TimeoutExpired carries whatever the process printed before we killed it, and
    carries it as bytes when the stream was never decoded. Either way it is evidence."""
    if not chunk:
        return ""
    return chunk.decode("utf-8", "replace") if isinstance(chunk, bytes) else chunk


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
        except subprocess.TimeoutExpired as e:
            # Everything the process managed to say before we killed it. Throwing
            # this away is how a deadlock reaches the model as the sentence "timed
            # out" — no file, no line, no cause — and no model can repair that.
            partial = _as_text(e.stdout) + _as_text(e.stderr)
            return False, f"`go {' '.join(args)}` timed out\n{partial}".strip()
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, out.strip()

    def build(self, cwd: str | Path) -> tuple[bool, str]:
        return self._run(["build", "./..."], cwd)

    def vet(self, cwd: str | Path) -> tuple[bool, str]:
        return self._run(["vet", "./..."], cwd)

    def test(self, cwd: str | Path) -> tuple[bool, str]:
        # -timeout, and it MUST be shorter than the subprocess timeout above.
        #
        # Go's own default is 10 minutes; ours was 5. So on a deadlock WE killed the
        # test binary first, and the model was handed "`go test ./...` timed out" —
        # a sentence with no file, no line and no cause in it. Go, left to hit its
        # own deadline, prints the goroutine dump, and that dump NAMES the deadlock:
        #
        #   store.(*MemStore).GetAccount(...)          <- takes RLock
        #   store.(*MemStore).CreateTransaction(...)   <- already holds Lock
        #
        # sync.RWMutex is not reentrant, and that trace says so in two lines. We were
        # killing the only witness and then asking the model to solve the murder.
        return self._run(["test", "-timeout", "60s", "./..."], cwd)

    def check(self, cwd: str | Path) -> tuple[bool, str]:
        """Run build, then vet, then test; stop at the first failure.

        Returns the combined output of the stage that ran. This is the feedback
        signal the agent loop fixes against — and how WIDE that signal is decides
        what the deterministic gates can repair, because a gate cannot fix an
        error the compiler never printed.

        Each stage sees a different slice of the truth, so a failing check
        harvests all of them:

        * ``go build`` never compiles ``_test.go`` files at all, so a broken impl
          hides every test-file error behind it.
        * ``go vet`` does typecheck the tests, but it bails at the FIRST type
          error in a package — one diagnostic, then silence.
        * ``go test`` compiles the test binary and the compiler reports up to ten
          errors per package. In practice this is the widest surface by far: on a
          real artifact vet reported a single ``undefined: NewStore`` while test
          reported ten errors, including a shadowed-``t`` bug three files away
          that no gate could otherwise have seen.

        So when the project does not compile we run all three and concatenate,
        which lets the gates and the per-file routing clear a whole layer of
        mechanical defects in ONE round instead of peeling them off one per round.
        """
        ok, out = self.build(cwd)
        if not ok:
            for stage in (self.vet, self.test):
                s_ok, s_out = stage(cwd)
                if not s_ok and s_out:
                    out = f"{out}\n{s_out}".strip()
            return False, out
        vet_ok, vet_out = self.vet(cwd)
        if not vet_ok:
            # vet stopped at its first type error; test carries the rest.
            t_ok, t_out = self.test(cwd)
            if not t_ok and t_out:
                vet_out = f"{vet_out}\n{t_out}".strip()
            return False, vet_out
        ok, out = self.test(cwd)
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


def rule_disabled(name: str) -> bool:
    """True when GUILDLM_DISABLE_RULES names this prompt default — an A/B switch.

    Every prompt default in this file earned its place by being MEASURED against
    its own absence: list_rule, routing_rule, mutex_rule, completeness_rule. Each
    time, the arm-off switch was a one-off env guard hand-added for the
    experiment and deleted after — and deleting it is what makes the NEXT
    question expensive. The completeness rule's own value on a prose-heavy spec
    (shortener) is untested right now for exactly that reason: the guard that
    could answer it was removed the moment it had answered the previous one.

    The alternative to a switch here is running the off-arm from an older commit,
    which silently changes MORE than the rule under test and confounds the
    experiment it was meant to settle.

    So the off-switch is part of the method, not scaffolding around it:
        GUILDLM_DISABLE_RULES=completeness ./_ab_run.sh shortener
    Names are the rule's own, comma-separated. Unknown names are ignored — this
    is a measuring instrument, not a config the build depends on.
    """
    raw = os.environ.get("GUILDLM_DISABLE_RULES", "")
    return name in {p.strip() for p in raw.split(",") if p.strip()}


def rule_enabled(name: str) -> bool:
    """True when GUILDLM_ENABLE_RULES names this default — the opt-IN side.

    For a rule that is OFF by default because its benefit did not reproduce, but
    whose idea has not been disproven either. `completeness` is the first: it
    recovers a named test the model drops on workapi (3/3, real, and invisible to
    coverage), and it costs shortener its green (5/5). It stays in the tree,
    switched off, so the next person to measure it does not have to rebuild it —
    and so the day it earns its way back the diff is one word, not a rewrite.

    Deleting it instead would throw away the workapi finding along with the rule.
    """
    raw = os.environ.get("GUILDLM_ENABLE_RULES", "")
    return name in {p.strip() for p in raw.split(",") if p.strip()}


def _retrieval_block(shots: Sequence[tuple[str, str]] | None) -> str:
    if not shots:
        return ""
    parts = [
        "Similar verified Go examples for reference (these compile; adapt the "
        "idiom to the spec, do not copy verbatim). The examples teach STYLE and "
        "testing SHAPE only — constructor and function SIGNATURES always come "
        "from THIS project's own files shown below, never from an example (an "
        "example's NewX may take fewer or different arguments than this "
        "project's NewX):\n"
    ]
    for instr, resp in shots:
        parts.append(f"# Example task: {instr}\n{resp}\n")
    parts.append("\n")
    return "".join(parts)


def _test_rule(path: str) -> str:
    """The test-authoring defaults. Hoisted to module scope because the FIX
    prompt needs them too: for a week these rules were handed to the generator
    and withheld from the fixer, so every fix round rewrote a test file blind to
    every default the project had built — and regressed to the unguided prior it
    was written to prevent. The drained-body bug came back that way, through four
    fix rounds, against a default that quotes the wrong code verbatim."""
    if not path.endswith("_test.go"):
        return ""
    # THE MODEL DROPS TESTS THE SPEC ASKED FOR — including ones it NAMES.
    # ratelimit's spec asks for HTTP flow tests through a hit() helper; the model
    # wrote three easy unit tests, defined hit(), never called it, and left the
    # middleware/router/handlers at ZERO coverage: 42.4% behind a GREEN suite.
    # With this sentence it wrote the flow tests and coverage returned to 75.4%
    # (2/2, from a stable 42.4 baseline).
    #
    # It is not only prose-described tests that go missing. workapi's spec NAMES
    # TestListSorted in so many words, and a controlled A/B — workapi x3 per arm,
    # one server, arms alternated — showed the model DROPPING IT at generation
    # every run without this rule and WRITING IT every run with it (3/3 vs 3/3,
    # caught pre-gate, so it is the model's own behaviour).
    #
    # I kept ratelimit's own specifics in this wording on the grounds that the
    # 42.4 -> 75.4 recovery was evidence for THAT text and a principle-only
    # rewrite would be unproven. The specifics then broke a spec, 3/3:
    #
    #   shortener, A/B, alternating arms, one server
    #     with the rule:    10 test funcs, 0.0% coverage, NOT-GREEN  (x3)
    #     without the rule:  2 test funcs, 72.7% coverage, GREEN     (x2)
    #     vet: ./shortener_test.go:58:36: not enough arguments in call to doReq
    #
    # The rule's half that WORKS is confirmed even there — 2 test functions
    # become 10, exactly as designed. What fails is the assumption I bolted onto
    # it: that more tests means more coverage. The model cannot keep 10 of them
    # coherent, so the file does not compile and coverage goes 72.7 -> 0.0.
    #
    # The discriminator is this project's own law, and my default was the victim:
    #     grep -c "func hit(h http.Handler" specs/ratelimit.yaml  -> 1  (SHOWN)
    #     grep -cE "func (doReq|hit|newReq)" specs/shortener.yaml -> 0  (nothing)
    # ratelimit's spec SHOWS the helper's code in full, so demanding flow tests
    # through it works. shortener's shows nothing, so the same demand makes the
    # model INVENT a helper and miscall it. The held-out ledger already taught
    # this: a mechanical construct that is DESCRIBED rather than SHOWN is where
    # the model breaks — the cure is to show the code. This wording imported
    # ratelimit's shape into every test file, and only ratelimit's spec has the
    # code to back it.
    #
    # So: keep the principle, drop the specifics, and say plainly that a helper
    # the purpose did not show must not be invented. Both re-runs were then
    # required, and both were run. THE RULE DID NOT SURVIVE THEM, so it is OFF BY
    # DEFAULT — opt in with GUILDLM_ENABLE_RULES=completeness to measure it.
    #
    # shortener, generalised wording: the invention is gone (0 invented helpers,
    # vet clean, 0.0 -> 64.6) and the green is still not back, 2/2. The model now
    # writes the flow tests and GUESSES the short code (`/r/0`) instead of using
    # the Link that Save() returns, so Redirect 404s. One mask off, the next one
    # underneath.
    #
    # ratelimit — the founding evidence — DID NOT REPRODUCE. Two server
    # processes, seven arms:
    #     server up 09:27:   with 74.6 / without 74.6   (rule: NO effect)
    #     server up 17:09:   with 75.0 / without 75.0   (rule: NO effect)
    # The 42.4 baseline that justified this rule never came back; the OFF arm
    # writes the flow tests by itself, calling hit() four times. And read 74.6 vs
    # 75.0 closely: identical code, identical prompts, different server PROCESS.
    # Every determinism measurement behind today's reasoning — three 1200-token
    # completions byte-identical, A/B/A identical — was taken WITHIN one process.
    # The true statement is DETERMINISTIC WITHIN A PROCESS, DIFFERENT ACROSS
    # PROCESSES, which is also the shape of the old 75.0 -> 42.4 drift. The +33
    # was measured against a baseline that belonged to one process's state.
    #
    # The ledger, on today's evidence:
    #     ratelimit   0 effect       (2 processes, 7 arms)
    #     workapi     +1 test        (TestListSorted, 3/3, pre-gate — real, and
    #                                 invisible to coverage: sorted and unsorted
    #                                 code execute the same lines)
    #     shortener   loses green    (5/5, across BOTH wordings)
    # A cost that reproduces and a benefit that does not. A default does not ship
    # on that, however much I want the idea to be true.
    #
    # WHAT WOULD EARN IT BACK, in order: (1) fix shortener's SPEC — it names no
    # tests and never says to use Save's return, and this project's law is that
    # implicit means broken and that naming is the spec-writer's job; (2) re-run
    # shortener — if the break was the spec's, the cost disappears and the workapi
    # gain stands alone; (3) reproduce the 42.4 failure mode deliberately before
    # ever claiming again that this rule prevents it.
    completeness = (
        "" if not rule_enabled("completeness") else
        "WRITE A FOCUSED TEST FUNCTION FOR EVERY SCENARIO "
        "the purpose describes — do NOT stop at the easy unit tests. Count the "
        "distinct scenarios the purpose names above and write one focused "
        "function for each. If the purpose SHOWS a helper, call it from every "
        "test that needs it: a helper you define and never call means you "
        "dropped the very tests it exists for, leaving the code it would have "
        "reached at zero coverage — a suite that passes trivially and proves "
        "almost nothing. Do NOT invent a helper the purpose did not show; write "
        "those steps inline in each test instead.\n"
    )
    return (
        "This is a TEST file. " + completeness +
        "Derive every expected value strictly from the "
        "behaviour described above for the functions under test — do not invent "
        "edge cases whose expected result contradicts those stated rules. If you "
        "are unsure what an exotic input (emoji, combining marks, mixed scripts) "
        "should produce under the rules, omit that case rather than guess.\n"
        "ISOLATE STATE, THEN SEED IT: each test case MUST construct its OWN fresh "
        "instance of the system under test — never share one mutable instance "
        "across cases, or state left by an earlier case makes a later one fail "
        "spuriously. Build the thing that HOLDS THE STATE, not merely a wrapper "
        "over it: a router/mux/handler is stateless, and the store (or registry, "
        "or cache) underneath is what remembers. A fresh `mux := NewRouter(reg)` "
        "over a registry built ONCE outside the cases isolates NOTHING — an "
        "earlier case has already spent clientA's only token, so this one gets 429 "
        "where it expects 200 and no implementation can make it pass. Construct "
        "BOTH inside each case: the store/registry first, then the handler over "
        "it. But a fresh instance is EMPTY, and "
        "that is the other half of the rule: any case with a PRECONDITION must "
        "CREATE that precondition ITSELF, first, in its own body. A 'duplicate -> "
        "409' case must POST the record ONCE (expect 201) and only then POST it "
        "AGAIN; a 'get/update/delete an existing X' case must POST X first. On a "
        "store nobody has written to, a duplicate returns 201 and an 'existing' "
        "record returns 404 — the case fails no matter how correct the handler is. "
        "For stateful CRUD, therefore, prefer SEPARATE FOCUSED TEST FUNCTIONS "
        "(each seeding what it needs) over one shared table loop, which pushes you "
        "toward exactly this mistake. Declare every local with := in the scope "
        "that uses it.\n"
        "ONE TEST FUNCTION, ONE OUTCOME. If you do reach for a table, every row in "
        "it must expect the SAME KIND of result, because the assertion after the "
        "loop is SHARED and can only express one. A loop whose check is `if err == "
        "nil { t.Errorf(...) }` DEMANDS an error from every row — so a row that "
        "expects nil (say, a valid \"done\" status dropped into a bad-status table) "
        "is unsatisfiable by construction: it fails against a CORRECT "
        "implementation, and no code you can write will make it pass. Keep the "
        "nil-expecting cases in the function that asserts nil, and the "
        "error-expecting cases in the function that asserts an error.\n"
        "TEST A REJECTION ON A VALUE YOU BUILT, NOT ONE YOU LOADED. A constructor "
        "that VALIDATES before it returns (Load/New/Parse) can never hand you an "
        "invalid value — that is its whole job. On failure it gives back the ZERO "
        "value, and the zero value usually PASSES the very check you were trying to "
        "fail. Worse, a loader that treats an EMPTY environment variable as UNSET "
        "will substitute the DEFAULT: setting AUTH_TOKEN=\"\" and calling Load() "
        "yields the default \"secret\", a NON-empty token, so Validate() correctly "
        "returns nil and your 'empty token is rejected' test fails against a CORRECT "
        "implementation. The invalid state is UNREACHABLE through the constructor by "
        "construction. So to test that Validate() REJECTS something, build the "
        "invalid value DIRECTLY as a field-named literal and call Validate() on it. "
        "Validate's contract is about a value; test it on a value.\n"
        "ASSERT ON WHAT YOU JUST FETCHED: after a SECOND request, decode ITS "
        "response into a SEPARATE variable before asserting. Re-checking the slice "
        "you decoded from the FIRST response (e.g. asserting `len(all) <= 1` after "
        "a `?limit=1` request) tests nothing and fails no matter what the handler "
        "did — `all` still holds the earlier body.\n"
        "HTTP-TEST HYGIENE. Two different things are fresh at two different "
        "rhythms, and confusing them breaks the test either way:\n"
        "  * The ROUTER (and the store underneath it) is built ONCE PER TEST "
        "FUNCTION, bound to a variable, and REUSED for every request in that "
        "function. That is what isolates one test from another.\n"
        "  * The *http.Request and the ResponseRecorder are built FRESH FOR EVERY "
        "SINGLE ServeHTTP CALL.\n"
        "Never call newRouter() inline inside a ServeHTTP call, because then EVERY "
        "request gets its OWN EMPTY store: the POST that seeds the precondition "
        "writes to a store that is thrown away on the next line, so the 'duplicate' "
        "comes back 201, the 'existing' record comes back 404, and the list comes "
        "back empty — against a handler that is perfectly correct. Bind it once:\n"
        "    h := newRouter()   // ONE router, ONE store, for this whole test\n"
        "And never hand the same `req` to ServeHTTP twice. A request's Body is an "
        "io.Reader and the FIRST ServeHTTP DRAINS it, so a second call with the same "
        "req sends an EMPTY body: json.Decode fails on EOF and the handler answers "
        "400 — so a 'POST twice -> 409' case reports `want 409, got 400` against a "
        "handler that maps ErrExists to 409 perfectly correctly. Refreshing the "
        "RECORDER is not enough and is not the point: `w = httptest.NewRecorder()` "
        "followed by `h.ServeHTTP(w, req)` with the SAME req is exactly the bug. "
        "THE DUPLICATE TEST IS WHERE THIS BITES, AND ONLY THERE. Everywhere else "
        "the second request is a different method or a different URL (GET, DELETE, "
        "a list), so you are forced to build a new one and the bug cannot happen. "
        "The duplicate case is the ONE test in which both requests are a POST of "
        "the SAME body to the SAME URL — which is exactly what makes reusing `req` "
        "look correct. It is not. Build TWO requests there, from TWO fresh readers "
        "over the same body string. This shape belongs in the duplicate test and "
        "nowhere else — do not copy it into a test that merely happens to send two "
        "POSTs of DIFFERENT bodies (a list test), which needs no such care:\n"
        "    h := newRouter()                            // once — keeps the state\n"
        "    req1 := httptest.NewRequest(\"POST\", \"/tasks\", "
        "bytes.NewBufferString(body))\n"
        "    h.ServeHTTP(httptest.NewRecorder(), req1)   // seed it (same h) -> 201\n"
        "    req2 := httptest.NewRequest(\"POST\", \"/tasks\", "
        "bytes.NewBufferString(body))  // SAME body, SECOND reader\n"
        "    w := httptest.NewRecorder()\n"
        "    h.ServeHTTP(w, req2)                        // same h -> now it IS a duplicate -> 409\n"
        "When a case wants 'malformed JSON', send genuinely "
        "unparseable bytes like `{\"x\":` (truncated) — NOT valid-but-empty `{}`, "
        "which decodes fine and returns 201.\n"
        # Twice in one sweep the model wrote the status-code check the spec asked
        # for and then INVENTED a second assertion about the response body — a
        # health check whose body is the bare JSON string "ok" decoded into a
        # struct (zero value, red), and a malformed-JSON case asserted against a
        # validation message the request never reaches (json.Decode fails first,
        # so Validate is never called, so that error does not exist). Both failed a
        # handler that was working correctly. The spec named the assertion and not
        # its BOUNDARY, and the model filled the silence.
        "WHEN THE EXPECTED OUTCOME IS A STATUS CODE, ASSERT THE STATUS CODE AND "
        "NOTHING ELSE. Do not invent a second assertion about the response body. "
        "You do not know the body's shape unless the spec names it, and a guess "
        "that is wrong fails a handler that is working correctly: a body that is "
        "the bare JSON string \"ok\" decodes into a struct as the ZERO VALUE, and "
        "a malformed-JSON request fails at json.Decode — so Validate() is never "
        "reached and the validation message you are asserting on does not exist. "
        "If the spec names the body, assert exactly that. If it does not, the "
        "status code IS the test.\n"
        "STRUCT LITERALS: write every struct value with its FIELD NAMES (e.g. "
        "`models.Task{ID: \"1\", Status: \"todo\"}`, or a table case "
        "`{name: \"x\", want: 404}`), never a positional literal — a positional "
        "literal silently assigns values to the WRONG fields when the count or "
        "order is off (e.g. an int status code landing in a string field), and "
        "`go vet` does NOT flag this for a same-package struct. This bites "
        "table-of-cases structs the most.\n"
        "NAMING: a test function is `func TestX(t *testing.T)` — NEVER declare a "
        "local variable named `t` inside it (e.g. `var t models.Task`), it "
        "shadows/redeclares the *testing.T and breaks every t.Fatalf after it. "
        "Name locals distinctly: got, want, task, rec, resp, err.\n\n"
    )


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
    test_rule = _test_rule(task.spec.path)
    # Registering routes with a Go 1.22+ ServeMux is a reliable small-model
    # trap: it writes the SAME bare pattern twice (List + Create both on
    # "/tasks"), which PANICS at startup ("conflicts with pattern") and fails
    # every test — a runtime panic the fix loop can't reason its way out of.
    routing_rule = (
        "ROUTING (Go 1.22+ ServeMux): register each route as METHOD + space + "
        "pattern, e.g. mux.HandleFunc(\"GET /tasks\", h.List) and "
        "mux.HandleFunc(\"POST /tasks\", h.Create). NEVER register the same bare "
        "pattern twice (two mux.HandleFunc(\"/tasks\", ...) calls) — ServeMux "
        "PANICS at startup. Register each handler by passing its method VALUE "
        "(`mux.HandleFunc(\"POST /tasks\", h.Create)`), never by CALLING it in "
        "the registration (not `h.Create(w, r)`) and never with an invented "
        "extra argument — a handler is an http.HandlerFunc `(w "
        "http.ResponseWriter, r *http.Request)` that reads path wildcards like "
        "{id} via r.PathValue(\"id\") and decodes the body itself.\n\n"
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
        "completely. Never reference a symbol you have not defined or imported.\n"
        "INTERFACE/IMPL PARITY & COMPLETENESS: implement every method an "
        "interface declares, and make sure every method a caller reaches through "
        "the type (a sibling file, or the method names listed in this file's own "
        "purpose) EXISTS on BOTH the interface and its implementation. When the "
        "two disagree, ADD the missing method — never drop it from the other side "
        "to make them 'match': a `var _ Iface = (*Impl)(nil)` assertion still "
        "passes when a required method is absent from BOTH sides, yet a caller's "
        "`x.Method` is then undefined and the build fails.\n\n"
        if task.spec.path.endswith(".go") and not task.spec.path.endswith("_test.go")
        else ""
    )
    # The plan splits a package into an interface file and an implementation file.
    # The model, writing the interface file, helpfully implements it there too —
    # and then the implementation file has nothing left to declare, its candidate
    # is stripped of every symbol its sibling already owns, and it ships as a bare
    # `package store`. EVERY multi-package spec in the suite carried one of these
    # dead files (workapi, taskapi, taskapipro, tasks-api). The project still
    # compiles — Go does not care which file in a package holds what — so nothing
    # ever complained.
    _siblings = [
        f.path for f in spec.files
        if f.path != task.spec.path
        and f.path.endswith(".go") and not f.path.endswith("_test.go")
    ]
    scope_rule = (
        "STAY IN YOUR LANE: write ONLY what THIS file's purpose asks for. The "
        "plan above gives the other files their own jobs — if another file is "
        "responsible for something (the in-memory implementation, the handlers, "
        "the router), do NOT also write it here. Doing its job leaves that file "
        "nothing to declare, it ships EMPTY, and the project no longer matches the "
        "plan it was built from.\n\n"
        if _siblings and task.spec.path.endswith(".go")
        and not task.spec.path.endswith("_test.go")
        else ""
    )
    # container/list has a subtle API trap: PushFront/PushBack take the VALUE and
    # create the *list.Element for you. A small model often hand-builds a
    # &list.Element{Value: v} and passes THAT, which the compiler accepts (both are
    # `any`) but which double-wraps — so a later el.Value.(*entry) panics at
    # runtime, never at compile time. Teach the idiom where the file uses the list.
    list_rule = (
        "CONTAINER/LIST IDIOM: ll.PushFront(v) and ll.PushBack(v) take the VALUE "
        "to store and RETURN the *list.Element they create for you, so capture it "
        "(`el := ll.PushFront(&entry{...})`). NEVER hand-build a "
        "`&list.Element{Value: v}` and pass that to PushFront/PushBack — it "
        "compiles (both are `any`) but double-wraps the value, so a later "
        "`el.Value.(*entry)` panics at runtime. Read a stored value back with "
        "`el.Value.(*entry)`, and ll.Remove(el) / ll.MoveToFront(el) take the "
        "element itself.\n\n"
        if (task.spec.path.endswith(".go")
            and re.search(r"container/list|list\.(?:List|Element)|"
                          r"MoveToFront|Push(?:Front|Back)",
                          task.spec.purpose))
        else ""
    )
    # sync.RWMutex/Mutex is NOT reentrant. A method that holds the write lock
    # and, while holding it, calls a SIBLING method that read-locks the SAME
    # mutex deadlocks the goroutine forever — the compiler cannot see it; it
    # surfaces only as a test timeout with a goroutine dump the model cannot
    # reason its way out of. The held-out ledger burned five whole fix rounds on
    # exactly this (CreateTransaction held Lock() and called GetAccount, which
    # RLocks). It is a standard-idiom failure — a real Go developer never nests
    # the two — so teach it wherever a file guards state with a mutex.
    # The wording above is entirely CROSS-METHOD ("call another method of this
    # type"). shortener 2026-07-17 showed the INTRA-METHOD case it does not cover,
    # 4/4 in one process: a single Resolve() that RLock()s to read, then — still
    # holding the read lock — Lock()s to write. A read lock cannot be upgraded to
    # a write lock on the same RWMutex; it blocks forever. mutex_rule fires on the
    # file and the model, reading a rule about A-calls-B, still writes the
    # lock-yourself-twice bug. The extra sentence is gated behind a switch so it
    # ships zero blast radius until an A/B earns it: current wording is the OFF
    # arm (already measured, 4/4 deadlock in PID 3082), extended wording the ON.
    mutex_intra = (
        " AND DO NOT LOCK YOURSELF TWICE: a SINGLE method must take the lock ONCE. "
        "If it needs to WRITE, take mu.Lock() at the TOP — never RLock() to read "
        "and then Lock() to write later in the SAME method (a read lock cannot be "
        "upgraded to a write lock on the same RWMutex; it DEADLOCKS forever, a test "
        "TIMEOUT, no compile error). A method that mutates ANY shared field — even "
        "one counter, like Hits++ — is a WRITER: Lock() once at the top, no RLock "
        "anywhere in it."
        if rule_enabled("mutex_intra") else ""
    )
    mutex_rule = (
        "MUTEX REENTRANCY (sync.Mutex / sync.RWMutex is NOT reentrant): once a "
        "method has taken the lock — mu.Lock() or mu.RLock() — it must NOT, "
        "while still holding it, call another method of this type that locks "
        "the SAME mutex. A write method holding mu.Lock() that calls a read "
        "accessor doing mu.RLock() (e.g. CreateX/Apply calling GetX/Exists) "
        "DEADLOCKS forever, and it shows up only as a test TIMEOUT, never a "
        "compile error. While holding the lock, touch the shared fields/maps "
        "DIRECTLY (`m.items[id]`, `_, ok := m.items[id]`) instead of calling "
        "the accessor methods." + mutex_intra + "\n\n"
        if (task.spec.path.endswith(".go")
            and not task.spec.path.endswith("_test.go")
            and not rule_disabled("mutex")
            and re.search(r"sync\.(?:RW)?Mutex", task.spec.purpose))
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
        f"{scope_rule}"
        f"{list_rule}"
        f"{mutex_rule}"
        f"{test_rule}"
        f"Write the complete contents of {task.spec.path}. "
        f"Use only the Go standard library. Output one fenced ```go block."
    )


def _fix_prompt(
    task: FileTask,
    current: str,
    error_output: str,
    siblings: dict[str, str] | None = None,
    shots: Sequence[tuple[str, str]] | None = None,
) -> str:
    """Prompt asking the coder to repair one file given toolchain errors.

    ``siblings`` are the project's other already-written files. Without them a
    model cannot tell that a "redeclared in this block" error means *its own*
    copy of a symbol is the duplicate to delete — it only sees the one file.

    ``shots`` are role-matched verified examples (same retrieval as
    generation). A fixer without them regresses to its unguided prior on
    exactly the failures grounding was added to prevent — it repeats the same
    broken assertion shape round after round.
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
    # The dominant runtime-failure mode the fixer faces in subtest suites is
    # state pollution — and a regenerated fix keeps the same shared-instance
    # shape unless told the diagnosis explicitly.
    if is_assertion_failure and task.spec.path.endswith("_test.go"):
        assertion_rule += (
            "MOST COMMON ROOT CAUSE in t.Run/table suites: every case SHARES "
            "one mutable store/server/handler built once at the top, so an "
            "earlier case's inserts/deletes leak into later cases (symptoms: "
            "got contains records this case never created; a record the case "
            "expects is already deleted; counts are off by earlier cases). "
            "THE FIX: construct a FRESH store/server INSIDE each t.Run subtest "
            "or loop body and create that case's fixture records there — no "
            "package-level or top-of-function shared instance.\n\n"
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
        # The test-authoring defaults, which for a week reached the GENERATOR and
        # never the FIXER. A fix round rewrites the whole file; without these it
        # rewrites it blind to every rule the project has built, and reverts to
        # the prior each one exists to prevent. That is how the drained-body bug
        # returned — through four fix rounds, against a default that quotes the
        # wrong code verbatim and predicts its exact symptom. The fixer was never
        # shown it.
        f"{_test_rule(task.spec.path)}"
        f"{_retrieval_block(shots)}"
        f"{sibling_block}"
        f"--- current {task.spec.path} ---\n{current}\n"
        f"--- toolchain output ---\n{_canonical_toolchain_output(error_output)}\n\n"
        f"Output the corrected complete file as one fenced ```go block."
    )


# `ok  \tpkg\t0.710s` / `ok  \tpkg\t(cached)` / `--- FAIL: TestX (0.00s)`.
_GO_PKG_TIME_RE = re.compile(r"\t(?:\d+(?:\.\d+)?s|\(cached\))(?=\t|$)", re.MULTILINE)
_GO_CASE_TIME_RE = re.compile(r"(--- (?:FAIL|PASS|SKIP): \S+) \(\d+(?:\.\d+)?s\)")


def _canonical_toolchain_output(error_output: str) -> str:
    """Strip the run-to-run noise out of go's output BEFORE it reaches the model.

    The fix prompt embeds toolchain output verbatim, and that output carries text
    that changes between runs of identical code: per-package durations (`0.710s`),
    per-test durations (`--- FAIL: TestX (0.00s)`), and — worst — `(cached)`,
    which go substitutes for a duration when its GLOBAL, MACHINE-WIDE test cache
    already holds the answer.

    That last one makes a run depend on the runs before it: the cache is global
    and machine-wide, so the 6th run of a spec can be handed text the first five
    never saw. It demonstrably reaches the model — in the A/B behind 612c4f3 the
    6th run's `(cached)` lines sit in the toolchain output of fix rounds 3, 4 and
    5, which is to say inside the prompts of rounds 4 and 5.

    WHAT THIS DOES NOT CLAIM — and what 0fe717f's message wrongly did. That 6th
    run is also the only one that diverged and went red, and I wrote the obvious
    story: the cache contaminated it. The timeline refutes me. Its `(cached)`
    lines first appear in round 3, but it had already left its arm's path in
    round 1 — its first vet error is `undefined: fakeEnqueuer` at line 24 where
    its sibling run's is `undefined: failStore` at line 165. The divergence
    PRECEDES the contamination, so the contamination cannot be its cause. If
    anything the arrow points the other way: a run only reaches the test stage,
    where `(cached)` can appear at all, once it is limping — some packages
    passing, others failing.

    So: a real contaminant, correctly removed, with a false story attached.
    Stripping it stands on its own terms — cache state and wall-clock durations
    are the prompt's only moving parts carrying ZERO information (a duration
    cannot tell you why `failStore` is undefined), and a prompt should be a
    function of the code. But it does not explain the red, and the question it
    was supposed to answer is still OPEN: generation is deterministic (measured:
    three 1200-token completions at temp=0.1, byte-identical) and yet same-arm
    runs generate DIFFERENT files. Something upstream of the fix loop varies per
    process. Look there, not here.
    """
    return _GO_CASE_TIME_RE.sub(r"\1", _GO_PKG_TIME_RE.sub("", error_output))


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


def _widen_runtime_targets(
    targets: list[str],
    written: dict[str, str],
    runtime_rounds: dict[str, int],
    error_output: str,
) -> list[str]:
    """Root-cause widening for PERSISTENT runtime test failures.

    A failing assertion is attributed to the *test* file, but the genuine bug
    may live in the package's implementation (config.Load missing a default) —
    which the fixer can never touch while only the test file is targeted, so
    the loop stalls. First give the test author a round (the cheap, common
    case); if the SAME package still fails at runtime on a later round, add its
    implementation files to the targets so the model can repair whichever side
    actually violates the spec. Mutates ``runtime_rounds`` (dir -> failures
    seen). Pure aside from that — unit-testable without a toolchain."""
    if not _is_test_failure(error_output):
        return targets
    out = list(targets)
    for d in {_dir_of(t) for t in targets if t.endswith("_test.go")}:
        runtime_rounds[d] = runtime_rounds.get(d, 0) + 1
        if runtime_rounds[d] < 2:
            continue
        extra = [
            p for p in written
            if _dir_of(p) == d and p.endswith(".go")
            and not p.endswith("_test.go") and p not in out
        ]
        if extra:
            _log(f"  widening fix targets to package impl in {d or '.'} "
                 f"(persistent runtime failure)")
            out.extend(extra)
    return out


_UNDEF_PKGSYM_RE = re.compile(r"undefined: (\w+)\.(\w+)")

# `x.Update undefined (type Store has no field or method Update)` — the
# missing method belongs on the TYPE, declared in another file.
#
# The compiler writes that type THREE ways, and the routing was deaf to two of them:
#   type Store           has no field or method Update      (same package)
#   type *service.Ledger has no field or method Transactions (pointer + qualified)
#   type service.Ledger  has no field or method Transactions (qualified)
# Held-out ledger burned three fix rounds regenerating the CALLER — the only file it
# was ever offered — while the fix (add the method) belonged to a file in another
# package that the widener would have added, had it recognised the sentence. The
# mechanism was right and silent, which is the most expensive way for one to be wrong.
# A stdlib receiver still cannot widen anything: no project file declares `type Request`.
_NOMETHOD_RE = re.compile(r"type \*?(?:\w+\.)?(\w+) has no field or method (\w+)")


def _widen_promised_symbol_targets(
    targets: list[str],
    written: dict[str, str],
    error_output: str,
    files: Sequence[FileSpec],
) -> list[str]:
    """Root-cause widening for a SINGLE-package project, where the compiler has
    no package name to point at. ``undefined: NewStore`` is reported in
    store_test.go — the USE site — so the fix loop keeps regenerating the test,
    while the real defect is that store.go named its constructor NewStoreImpl.
    The loop can thrash all five rounds on the wrong file and never converge.

    The spec knows who was supposed to declare it: store.go's purpose says the
    constructor is named EXACTLY ``NewStore``. So when a symbol is undefined and
    NO file in the project declares it, add the non-test file whose purpose
    PROMISES that symbol. Routing only — it changes which file the model is asked
    to regenerate, never the code — and it stays silent unless exactly one file
    claims the symbol, so it cannot pull an unrelated file into the fix."""
    declared: set[str] = set()
    for p, c in written.items():
        if p.endswith(".go"):
            declared |= top_level_decls(c)
    out = list(targets)
    missing = {m.group(2) for m in _UNDEF_BARE_RE.finditer(error_output)}
    for sym in missing:
        if sym in declared or not sym[:1].isupper():
            # Either it exists somewhere (a qualification miss, not ours), or it
            # is unexported — an undefined lowercase symbol is a local typo, not
            # a top-level declaration a purpose could have promised, and a
            # purpose mentioning the word in prose must not drag its file in.
            continue
        owners = [
            f.path for f in files
            if f.path.endswith(".go") and not f.path.endswith("_test.go")
            and re.search(rf"\b{re.escape(sym)}\b", f.purpose or "")
        ]
        if len(owners) != 1 or owners[0] in out:
            continue  # nobody claims it, or several do — do not guess
        _log(f"  widening fix targets to {owners[0]} — undefined {sym}, "
             f"which its purpose promises it declares")
        out.append(owners[0])
    return out


def _widen_missing_symbol_targets(
    targets: list[str], written: dict[str, str], error_output: str
) -> list[str]:
    """Compile-time root-cause widening. ``undefined: models.Event`` is reported
    at the USE site (service.go), but the fix belongs at the DEFINITION site — the
    ``models`` package, whose file omitted the Event type the spec requires. While
    only the use-site is targeted the loop oscillates and never adds the type.
    When a project package is referenced for a symbol NONE of its files declare,
    add that package's non-test files to the targets so the model regenerates the
    owner (whose spec lists the missing type). Pure — unit-testable without go."""
    pkg_dir: dict[str, str] = {}
    for p, c in written.items():
        name = pkg_name_of(c)
        if name and name != "main":
            pkg_dir.setdefault(name, _dir_of(p))
    decls_by_dir: dict[str, set[str]] = {}
    for p, c in written.items():
        decls_by_dir.setdefault(_dir_of(p), set()).update(top_level_decls(c))
    out = list(targets)
    for m in _UNDEF_PKGSYM_RE.finditer(error_output):
        pkg, sym = m.group(1), m.group(2)
        d = pkg_dir.get(pkg)
        if d is None or sym in decls_by_dir.get(d, set()):
            continue  # not ours, or the symbol exists (a qualification miss)
        extra = [
            p for p in written
            if _dir_of(p) == d and p.endswith(".go")
            and not p.endswith("_test.go") and p not in out
        ]
        if extra:
            _log(f"  widening fix targets to {d or '.'} — undefined "
                 f"{pkg}.{sym} (missing from its package)")
            out.extend(extra)
    # `a.store.Update undefined (type Store has no field or method Update)` —
    # reported at the CALL site, but the fix is on the type: the interface
    # (and often its concrete impl) must gain the method. Add the file
    # DECLARING the type so the model can actually make the change.
    #
    # But NOT when the receiver is the shadowed tester: `t.Fatalf undefined (type
    # Task has no field or method Fatalf)` reads identically and is a completely
    # different bug — a loop variable named t stole the *testing.T. Widening on it
    # drags models.go into the fix and invites the model to give Task a Fatalf
    # method, which is nonsense. _fix_shadowed_tester owns that error.
    shadowed = {(m.group(2), m.group(1)) for m in _SHADOWED_T_RE.finditer(error_output)}
    for m in _NOMETHOD_RE.finditer(error_output):
        typ = m.group(1)
        if (typ, m.group(2)) in shadowed:
            continue
        decl_re = re.compile(rf"^type\s+{re.escape(typ)}\b", re.MULTILINE)
        extra = [
            p for p, c in written.items()
            if p.endswith(".go") and not p.endswith("_test.go")
            and p not in out and decl_re.search(c)
        ]
        if extra:
            _log(f"  widening fix targets to the declaration of type {typ} "
                 f"(missing method {m.group(2)})")
            out.extend(extra)
    return out


def _log(msg: str) -> None:
    print(f"[guildlm-build] {msg}", file=sys.stderr, flush=True)


def _trace(record: dict) -> None:
    """Append one JSON line to the trace file named by GUILDLM_BUILDER_TRACE.

    The trace is the self-distillation tap: every ACCEPTED (prompt, response)
    pair is on-policy training data in the Builder's own inference format, and
    the run-final ``green`` event lets the harvester keep only pairs that a
    real toolchain verified end-to-end. No env var -> zero overhead."""
    path = os.environ.get("GUILDLM_BUILDER_TRACE")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:  # tracing must never kill a build
        _log(f"trace write failed ({e}); continuing without trace")


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


_METHOD_DECL_RE = re.compile(
    r"^func\s*\(\s*(?:\w+\s+)?\*?(\w+)(?:\[[^\]]*\])?\s*\)\s*(\w+)", re.MULTILINE
)


_MOVEDECLS = Path(__file__).resolve().parent.parent / "tools" / "movedecls.go"


def _fill_empty_planned_files(
    spec: "Spec",
    written: dict[str, str],
    out: Path,
    toolchain: GoToolchain,
) -> None:
    """Move a sibling's over-reach back into the file the plan gave it to.

    The plan splits a package: store.go declares the interface, memory.go
    implements it. The model writes both in store.go, memory.go has nothing left
    to declare, and it ships as a bare ``package store``. Every multi-package
    artifact in the suite carries one of these, the build is green regardless
    (Go's compilation unit is the package, not the file), and a prompt telling the
    model to stay in its lane did not stop it — so it gets a repair instead.

    Moving a declaration between files of the SAME package cannot change what the
    program means. That is what makes this safe rather than clever: the package is
    the compilation unit, imports are goimports' problem, and the move is checked
    afterwards anyway — if the project is not still green, it is reverted. Strictly
    non-regressing, like the review pass.
    """
    if not _MOVEDECLS.exists():
        return
    for path in empty_go_files(written):
        by_path = {f.path: f.purpose or "" for f in spec.files}
        wanted = _required_decls(by_path.get(path, ""))
        if not wanted:
            continue
        pkg = pkg_name_of(written[path])
        donor = None
        for p, c in written.items():
            if (
                p == path or not p.endswith(".go") or p.endswith("_test.go")
                or _dir_of(p) != _dir_of(path)
            ):
                continue
            # Only take back what the donor was NOT asked to declare. memory.go's
            # purpose mentions the Store interface because it implements it — but
            # declaring Store is store.go's job, and moving it would not fix the
            # plan, it would break it the other way.
            take = wanted - _required_decls(by_path.get(p, ""))
            if take and take <= (top_level_decls(c) | method_decls(c)):
                donor, wanted = p, take
                break
        if not donor or not pkg:
            continue
        try:
            proc = subprocess.run(
                ["go", "run", str(_MOVEDECLS), pkg, ",".join(sorted(wanted))],
                input=written[donor],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return
        if proc.returncode != 0 or not proc.stdout.strip():
            continue
        try:
            moved = json.loads(proc.stdout)
        except json.JSONDecodeError:
            continue

        before = {donor: written[donor], path: written[path]}
        written[donor] = _write_file(out, donor, moved["source"])
        written[path] = _write_file(out, path, moved["moved"])
        ok, _ = toolchain.check(out)
        if ok:
            _log(f"  moved {', '.join(sorted(wanted))} from {donor} into {path} — "
                 f"the plan gave that file the job")
        else:
            for p, c in before.items():
                written[p] = _write_file(out, p, c)
            _log(f"  left {path} empty: moving {', '.join(sorted(wanted))} into it "
                 f"does not stay green")


def empty_go_files(written: dict[str, str]) -> list[str]:
    """Implementation files that were generated but declare NOTHING — a bare
    `package store`. The spec asked for content there; a sibling wrote it instead,
    and the redeclaration stripper then emptied this file. Go compiles it happily,
    so only an explicit check ever notices."""
    return [
        p for p, code in sorted(written.items())
        if p.endswith(".go") and not p.endswith("_test.go")
        and not (top_level_decls(code) | method_decls(code))
    ]


def method_decls(code: str) -> set[str]:
    """Methods a Go file declares, as ``Receiver.Name`` strings (pointer/value
    receivers and generic type parameters normalized away). Dotted, so entries
    can share a set with ``top_level_decls`` names without colliding."""
    return {f"{recv}.{name}" for recv, name in _METHOD_DECL_RE.findall(code)}


def strip_redeclarations(code: str, forbidden: set[str]) -> str:
    """Delete top-level declarations (and their doc comments) whose name a
    SIBLING file already declares — the dominant failure when a small model
    writes a larger multi-file backend: it re-defines shared sentinels/types
    (e.g. store.go re-declares errors.go's ErrNotFound), an unrecoverable
    "redeclared in this block" error the fix loop bounces on. Deterministically
    removing the duplicate (the sibling owns it, same package) is the goimports-
    style repair. A METHOD is stripped only on an exact ``Receiver.Name`` match
    (dotted entries in ``forbidden``) — same receiver type, same package, which
    Go always rejects; mere name-sharing across types stays legal and is kept.
    Conservative: on any structural ambiguity it keeps the line."""
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
            pm = re.match(r"func\s+(\w+)", stripped)  # plain func, no receiver
            name = pm.group(1) if pm else None
            if name is None:  # a method: forbidden as dotted Receiver.Name
                mm = _METHOD_DECL_RE.match(stripped)
                if mm:
                    name = f"{mm.group(1)}.{mm.group(2)}"
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


def _gomod_content(module: str) -> str:
    """The go.mod for a stdlib-only project is fully determined by its module
    path — generate it deterministically rather than sampling a model (whose
    one bad sample turns every later diagnostic into go.mod parse noise)."""
    return f"module {module}\n\ngo 1.23\n"


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
# `\b` before the lookahead is load-bearing. Written as `(\w+)(?!\s*\.)` the
# engine backtracks: `undefined: NewStore` followed on the NEXT LINE by
# `./store_test.go:...` lets `\s*` cross the newline, the lookahead sees that
# leading dot, and the match shrinks to `NewStor` — a symbol that does not
# exist. `\b` forbids the shrink, so either the whole identifier matches or
# nothing does.
_UNDEF_BARE_RE = re.compile(r"([\w./-]+\.go):\d+:\d+: undefined: (\w+)\b(?!\.)")

# Stdlib packages a small model plausibly confuses symbols between. Order is
# the lookup order; first `go doc <pkg>.<Sym>` hit wins.
_STDLIB_CANDIDATES = (
    "time", "strings", "strconv", "fmt", "os", "io", "bytes", "errors",
    "sort", "math", "context", "sync", "bufio", "unicode", "regexp",
    "net/http", "encoding/json", "path/filepath", "slices", "maps",
)
_stdlib_owner_cache: dict[str, str | None] = {}

# Stdlib packages a model is liable to import as if they were its own — it writes
# `"guildlm.dev/workapi/internal/slog"` when it means `"log/slog"`. Keyed by the
# LAST segment, which is the name the code actually qualifies with.
_STDLIB_IMPORTABLE = (
    "log/slog", "net/http", "net/http/httptest", "encoding/json", "path/filepath",
    "sync/atomic", "math/rand", "os/signal", "time", "strings", "strconv", "fmt",
    "os", "io", "bytes", "errors", "sort", "math", "context", "sync", "bufio",
    "unicode", "regexp", "slices", "maps", "testing", "log", "flag",
)


def _stdlib_owner_of(sym: str) -> str | None:
    """Which stdlib package exports ``sym``? Resolved with the REAL toolchain
    (`go doc <pkg>.<sym>`), cached; None when no candidate (or several would
    need guessing — first hit in a deliberate order wins, which matches how
    ambiguity is rare for exported stdlib names a 7B actually confuses)."""
    if sym in _stdlib_owner_cache:
        return _stdlib_owner_cache[sym]
    owner = None
    for pkg in _STDLIB_CANDIDATES:
        try:
            r = subprocess.run(
                ["go", "doc", f"{pkg}.{sym}"], capture_output=True, timeout=10
            )
        except Exception:
            continue
        if r.returncode == 0:
            owner = pkg
            break
    _stdlib_owner_cache[sym] = owner
    return owner


def _requalify_stdlib(written: dict[str, str], error_output: str) -> dict[str, str]:
    """Deterministically fix a stdlib knowledge slip the compiler pinpoints:
    `undefined: strconv.ParseDuration` where the symbol actually lives in
    `time` -> rewrite `strconv.ParseDuration` to `time.ParseDuration` and
    ensure the owner import (goimports prunes the stale one). Only fires when
    the wrong qualifier is itself a stdlib candidate (a project package name
    is _requalify_undefined's job) and `go doc` confirms a unique owner."""
    changed: dict[str, str] = {}
    for m in _UNDEF_QUAL_RE.finditer(error_output):
        path, wrong, sym = m.group(1).lstrip("./"), m.group(2), m.group(3)
        if wrong not in {c.rsplit("/", 1)[-1] for c in _STDLIB_CANDIDATES}:
            continue
        if path not in written:
            cand = [p for p in written if p.endswith(path)]
            if len(cand) != 1:
                continue
            path = cand[0]
        owner = _stdlib_owner_of(sym)
        if not owner or owner.rsplit("/", 1)[-1] == wrong:
            continue
        code = changed.get(path, written[path])
        new = re.sub(rf"\b{re.escape(wrong)}\.{re.escape(sym)}\b",
                     f"{owner.rsplit('/', 1)[-1]}.{sym}", code)
        if new != code:
            changed[path] = _ensure_import(new, owner)
    return changed


# `package models is not in std (...)` — the model truncated a LOCAL import to
# some non-module form (bare "models", "internal/models", or the module tail
# "workapi/internal/models") instead of the full "guildlm.dev/workapi/internal/
# models". go reads the truncated path as a std-library lookup and fails.
# Deterministic and general — the real package directory is right there in the
# project. Same class as _requalify_stdlib: a mechanical, compiler-pinpointed slip.
_NOTINSTD_RE = re.compile(
    r"([\w./-]+\.go):\d+:\d+: (?:package (\S+) is not in std"
    r"|no required module provides package (\S+?);)"
)


def _fix_module_prefix(
    written: dict[str, str], error_output: str, module: str | None
) -> dict[str, str]:
    """Repair a local import that lost the module path. Resolves the truncated
    import to a real project package directory, then rewrites the literal to
    ``"<module>/<dir>"``. Handles every truncation the 7B produces:
      * bare basename            "models"                 -> internal/models
      * repo-relative dir        "internal/models"        -> internal/models
      * module tail + rest       "workapi/internal/models"-> internal/models
    A form is only rewritten when it resolves to EXACTLY ONE project package, so
    an ambiguous or genuinely-third-party miss is left alone."""
    if not module:
        return {}
    tail = module.rsplit("/", 1)[-1] if "/" in module else module
    dirs = {_dir_of(p) for p in written if _dir_of(p)}
    by_base: dict[str, list[str]] = {}
    for d in dirs:
        by_base.setdefault(d.rsplit("/", 1)[-1], []).append(d)

    def resolve(bad: str) -> str | None:
        if bad in dirs:                                   # "internal/models"
            return bad
        if "/" in bad:
            # corruption that still CONTAINS the real module path, e.g. a
            # hallucinated host prefix "github.com/<module>/internal/api"
            idx = bad.find(module + "/")
            if idx != -1:
                rest = bad[idx + len(module) + 1 :]
                return rest if rest in dirs else None
            # module tail + rest      "workapi/internal/models"
            rest = bad[len(tail):].lstrip("/") if bad.startswith(tail + "/") else ""
            return rest if rest in dirs else None
        cand = by_base.get(bad, [])                        # bare "models"
        return cand[0] if len(cand) == 1 else None

    changed: dict[str, str] = {}
    for m in _NOTINSTD_RE.finditer(error_output):
        path, bad = m.group(1).lstrip("./"), m.group(2) or m.group(3)
        target = resolve(bad)
        if not target:
            continue
        if path not in written:
            cand = [p for p in written if p.endswith(path)]
            if len(cand) != 1:
                continue
            path = cand[0]
        code = changed.get(path, written[path])
        new = code.replace(f'"{bad}"', f'"{module}/{target}"')
        if new != code:
            changed[path] = new
    return changed


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
                # Requalify EVERY bare use of the symbol, not just calls: the 7B
                # writes cross-package tests that use a sibling type in value AND
                # type position (`Enqueue(e Event)`, `[]Event`, `Task{...}`) while
                # only importing its own package. The compiler proved `name` is
                # undefined here, so every bare occurrence is the same foreign
                # symbol; `\b`+lookbehind keep `Events`, `wantEvents` and `.Field`
                # untouched. gofmt-on-write verifies the result stays valid Go.
                apply(path, rf"(?<![\w.]){re.escape(name)}\b(?!\s*\.)",
                      f"{owner}.{name}", owner)
    return changed


_ARITY_RE = re.compile(
    r"([\w./-]+\.go):(\d+):\d+: assignment mismatch: "
    r"(\d+) variables? but [\w.()\[\]*]+ returns (\d+) values?"
)

# `unknown field createErr in struct literal of type struct{...}` — ANONYMOUS
# inline structs only; a named type (models.Task) means the row is wrong, not
# the type, and is left for the model.
_UNKNOWN_FIELD_RE = re.compile(
    r"([\w./-]+\.go):(\d+):\d+: unknown field (\w+) in struct literal of type struct\{"
)

# `duplicate field name create in struct literal` — vet points at the LATER
# occurrence; deleting that line is the safe idempotent repair.
_DUP_FIELD_RE = re.compile(
    r"([\w./-]+\.go):(\d+):\d+: duplicate field name (\w+) in struct literal"
)


def _fix_duplicate_struct_fields(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """Drop the duplicated field line vet pinpoints in a struct literal (the
    same self-inconsistent-table family as _fix_unknown_struct_fields: the 7B
    sets the same field twice in one row). Only a line that is exactly a
    ``field: value,`` assignment for the reported field is deleted."""
    changed: dict[str, str] = {}
    for m in _DUP_FIELD_RE.finditer(error_output):
        path, lineno, field = m.group(1).lstrip("./"), int(m.group(2)), m.group(3)
        if path not in written:
            cand = [p for p in written if p.endswith(path)]
            if len(cand) != 1:
                continue
            path = cand[0]
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        if not re.match(rf"\s*{re.escape(field)}\s*:", lines[lineno - 1]):
            continue
        del lines[lineno - 1]
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
    return changed


def _infer_field_type(value: str) -> str | None:
    """Best-effort Go type of a struct-literal row value. None = don't guess."""
    v = value.strip().rstrip(",").strip()
    if not v:
        return None
    if re.fullmatch(r'"(?:[^"\\]|\\.)*"', v) or v.startswith("`"):
        return "string"
    if v in ("true", "false"):
        return "bool"
    if re.fullmatch(r"-?\d+", v):
        return "int"
    if re.fullmatch(r"-?\d*\.\d+", v):
        return "float64"
    if v == "nil" or "errors.New(" in v or "fmt.Errorf(" in v or re.search(r"\bErr[A-Z]\w*", v):
        return "error"
    m = re.fullmatch(r"(\[\][\w.]+)\{.*\}?", v, re.DOTALL)
    if m:
        return m.group(1)
    m = re.fullmatch(r"([\w.]+)\{.*\}?", v, re.DOTALL)
    if m and m.group(1)[0].isupper() or (m and "." in m.group(1)):
        return m.group(1)
    return None


def _fix_unknown_struct_fields(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """Deterministically complete an inline table-test struct: when a row uses
    a field the anonymous ``[]struct{...}`` declaration lacks (`unknown field X
    in struct literal of type struct{...}` — the 7B's self-inconsistent table),
    add ``X <type>`` to the declaration, inferring the type from the row value.
    Anonymous inline structs only; if the type can't be inferred or the decl
    can't be located unambiguously, the file is left for the model. Returns
    {path: new_content} for changed files only."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    for m in _UNKNOWN_FIELD_RE.finditer(error_output):
        path, lineno, field = resolve(m.group(1)), int(m.group(2)), m.group(3)
        if not path:
            continue
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        # the row value: everything after `field:` on the error line
        vm = re.search(rf"\b{re.escape(field)}\s*:\s*(.+)$", lines[lineno - 1])
        ftype = _infer_field_type(vm.group(1)) if vm else None
        if not ftype:
            continue
        # nearest preceding anonymous struct decl opener
        decl = None
        for i in range(lineno - 2, -1, -1):
            if re.search(r"\[\]struct\s*\{", lines[i]):
                decl = i
                break
        if decl is None:
            continue
        # its closing line: the first `}{` (decl ends, literal begins) below
        close = None
        for j in range(decl, min(lineno, len(lines))):
            if re.match(r"\s*\}\s*\{", lines[j]):
                close = j
                break
        if close is None:
            continue
        if re.search(rf"\b{re.escape(field)}\b", "\n".join(lines[decl:close])):
            continue  # already declared (another literal is the culprit)
        indent = re.match(r"\s*", lines[close - 1 if close > decl else close]).group(0)
        if close == decl + 1 or not lines[decl + 1:close]:
            indent = re.match(r"\s*", lines[decl]).group(0) + "\t"
        lines.insert(close, f"{indent}{field} {ftype}")
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
    return changed


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
            pad = ["_"] * (nvals - nvars)
            # `if err := f(); err != nil` carries the keyword into the LHS, so
            # split it off before deciding where the blanks go.
            head, _, bare = names[0].rpartition(" ")
            if len(names) == 1 and bare in ("err", "e"):
                # Go puts the error LAST. `err := svc.Create(...)` where Create
                # returns (Task, error) must become `_, err := ...`, never
                # `err, _ := ...` — which assigns the Task to `err`, so the
                # `err != nil` beside it is a type mismatch. This gate used to
                # append blindly and manufacture the exact bug
                # _fix_swapped_error_assignment exists to repair: one gate
                # breaking the code the next one fixes.
                names = pad + [bare]
                if head:
                    names[0] = f"{head} {names[0]}"
            else:
                # A value variable — `items := svc.List(ctx)` — keeps its slot,
                # and the error it ignored goes to the blank after it.
                names += pad
        indent = lhs[: len(lhs) - len(lhs.lstrip())]
        if sep == ":=" and all(n == "_" for n in names):
            sep = "="  # `_, _ :=` declares nothing — invalid Go
        lines[lineno - 1] = f"{indent}{', '.join(names)} {sep}{rhs}"
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
    return changed


# `string(i)` where i is an int yields a one-rune string, not the digits — a
# classic Go slip the toolchain flags. vet/compile pinpoint file:line:col.
_STRINT_RE = re.compile(
    r"([\w./-]+\.go):(\d+):(\d+): conversion from int(?:eger)? "
    r"to string yields a string of one rune"
)


def _fix_string_int_conversion(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """Rewrite the pinpointed ``string(<expr>)`` to ``strconv.Itoa(<expr>)`` and
    ensure the strconv import. Only the exact conversion the toolchain flags
    (at the reported column) is touched, so a legitimate ``string(byteslice)``
    elsewhere is never disturbed. Same mechanical-class repair as the others."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    # Replace the flagged conversions first (same-line edits preserve line
    # numbers), then add the strconv import ONCE per file — inserting it earlier
    # would shift the line numbers of any later error in the same file.
    for m in _STRINT_RE.finditer(error_output):
        path = resolve(m.group(1))
        if not path:
            continue
        lineno, col = int(m.group(2)), int(m.group(3))
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        line = lines[lineno - 1]
        idx = line.find("string(", max(col - 1, 0))
        if idx == -1:
            idx = line.find("string(")
        if idx == -1:
            continue
        start = idx + len("string(")
        depth, j = 1, start
        while j < len(line) and depth:
            depth += (line[j] == "(") - (line[j] == ")")
            j += 1
        if depth:
            continue  # unbalanced on this line — leave it
        arg = line[start:j - 1]
        lines[lineno - 1] = f"{line[:idx]}strconv.Itoa({arg}){line[j:]}"
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
    return {p: _ensure_import(c, "strconv") for p, c in changed.items()}


# The model reaches for github.com/pkg/errors — `errors.Wrap(err, "msg")` /
# `errors.Wrapf(err, "fmt", args...)` — which don't exist in the stdlib `errors`
# package, so the toolchain flags `undefined: errors.Wrap`. The stdlib idiom is
# fmt.Errorf with the %w verb. Rewrite the flagged call in place (line count
# preserved) and ensure fmt; goimports prunes the errors import if it is now
# unused, or keeps it when errors.Is/New/As remain.
_ERRWRAP_RE = re.compile(r"([\w./-]+\.go):(\d+):(\d+): undefined: errors\.(Wrapf?)\b")


def _split_top_level_args(s: str) -> list[str]:
    """Split a call's argument string on top-level commas, respecting nested
    (), [], {} and string/rune literals. Args are returned stripped."""
    args: list[str] = []
    buf: list[str] = []
    depth = 0
    quote: str | None = None
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if quote is not None:
            buf.append(ch)
            if ch == "\\" and quote != "`" and i + 1 < n:
                buf.append(s[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        args.append("".join(buf).strip())
    return args


def _wrap_to_errorf(msg: str, extra: list[str], err: str) -> str | None:
    """Build the fmt.Errorf(...) call for errors.Wrap/Wrapf. Only a string-literal
    message is handled (the overwhelmingly common case); a non-literal message
    returns None so it is left for the model rather than mis-transformed. The %w
    verb goes last, so the wrapped error becomes the final argument."""
    if len(msg) >= 2 and msg[0] == '"' and msg[-1] == '"':
        fmtlit = msg[:-1] + ': %w"'
    elif len(msg) >= 2 and msg[0] == "`" and msg[-1] == "`":
        fmtlit = msg[:-1] + ": %w`"
    else:
        return None
    return "fmt.Errorf(" + ", ".join([fmtlit] + extra + [err]) + ")"


def _fix_errors_wrap(written: dict[str, str], error_output: str) -> dict[str, str]:
    """Rewrite pkg/errors-style `errors.Wrap(err, "msg")` /
    `errors.Wrapf(err, "fmt", a...)` (undefined in the stdlib) to
    `fmt.Errorf("msg: %w", err)` / `fmt.Errorf("fmt: %w", a..., err)`. Same
    mechanical, compiler-pinpointed repair class as the other gates; only the
    flagged call is touched and line numbers are preserved."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    touched: set[str] = set()
    for m in _ERRWRAP_RE.finditer(error_output):
        path = resolve(m.group(1))
        if not path:
            continue
        lineno, col, fn = int(m.group(2)), int(m.group(3)), m.group(4)
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        line = lines[lineno - 1]
        needle = f"errors.{fn}("
        idx = line.find(needle, max(col - 1, 0))
        if idx == -1:
            idx = line.find(needle)
        if idx == -1:
            continue
        start = idx + len(needle)
        depth, j = 1, start
        while j < len(line) and depth:
            depth += (line[j] == "(") - (line[j] == ")")
            j += 1
        if depth:
            continue  # call spans multiple lines — leave it for the model
        args = _split_top_level_args(line[start:j - 1])
        if len(args) < 2:
            continue
        err_arg, msg_arg, extra = args[0], args[1], args[2:]
        if fn == "Wrap" and extra:
            continue  # Wrap takes exactly (err, msg)
        repl = _wrap_to_errorf(msg_arg, extra, err_arg)
        if repl is None:
            continue
        lines[lineno - 1] = line[:idx] + repl + line[j:]
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
        touched.add(path)
    return {p: _ensure_import(changed[p], "fmt") for p in touched}


# `declared and not used: u` (Go 1.20+) — the model captured an EXTRA return
# value it only needed to validate (or ignore) and never read, e.g.
# `u, err := url.ParseRequestURI(raw)` where only err is checked. The compiler
# pinpoints file:line:col and the name. Safe deterministic repair: blank the
# flagged name on a MULTI-value `:=` LHS (`u, err :=` -> `_, err :=`), keeping
# `:=` because a real new variable (err) remains. A LONE unused var
# (`x := expr`) is deliberately left to the model — there it usually means the
# value was meant to be used, and silently blanking it would mask that; the
# model regenerates the line with the intended use.
_UNUSED_VAR_RE = re.compile(
    r"([\w./-]+\.go):(\d+):(\d+): declared and not used:?\s*(\w+)"
)


# sync/atomic's Int64/Int32/Uint64/Uint32 have Add/Load/Store/Swap/CompareAndSwap
# and NO Inc/Dec. The model reaches for `.Inc()` — the name every other language
# gives this — and the compiler names the type, the method, the file and the line.
# It is the clearest sentence a gate could ask for, and the model STILL cannot act
# on it: told three times in one run, it rewrote `w.count.Inc()` three times, in a
# file where it used `w.count.Load()` correctly two lines below. That is the tell —
# not missing knowledge, a reflex. Which is the real criterion for a gate: not how
# OFTEN an error occurs, but whether the model can fix it once the compiler has
# named it. An error re-committed after being told is deterministic-layer work by
# definition, even at n=1.
# The SAME defect is reported in TWO sentences, and a gate that hears only one is
# deaf to half its job (Report #19's law, walked into while writing this gate):
#   go build : (type atomic.Int64 has no field or method Inc)
#   go vet   : (type "sync/atomic".Int64 has no field or method Inc)
# The quoted import path appears in one and not the other. Accept both.
_ATOMIC_INC_RE = re.compile(
    r"([\w./-]+\.go):(\d+):(\d+): ([\w.]+)\.(Inc|Dec) undefined "
    r"\(type (?:\"sync/atomic\"|atomic)\.(?:Int|Uint)\d+ "
    r"has no field or method (?:Inc|Dec)\)"
)


# `unknown field s in struct literal of type Ledger` — a NAMED type, so this is not
# the anonymous table-test struct that _fix_unknown_struct_fields completes (that one
# requires a literal `struct{` and will never match here). The two classes must not be
# confused: there the declaration is missing a field and we ADD one; here the field
# exists and the KEY is wrong, and adding `s` to Ledger would be a second bug.
_STRUCT_LIT_KEY_RE = re.compile(
    r"([\w./-]+\.go):(\d+):\d+: unknown field (\w+) in struct literal of type \*?(\w+)\b"
)
_STRUCT_DECL_RE = r"type\s+{name}\s+struct\s*\{{([^}}]*)\}}"


def _struct_fields(typename: str, written: dict[str, str]) -> list[tuple[str, str]] | None:
    """Field (name, type) pairs of a named struct declared somewhere in the project.

    Returns None when the type is declared in more than one place with different
    bodies — an ambiguous decl is one we must not guess about.
    """
    bodies: list[str] = []
    for code in written.values():
        for m in re.finditer(_STRUCT_DECL_RE.format(name=re.escape(typename)), code):
            bodies.append(m.group(1))
    if not bodies or len({b.strip() for b in bodies}) != 1:
        return None
    fields: list[tuple[str, str]] = []
    for raw in bodies[0].splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:  # embedded field, or something we do not model
            return None
        fields.append((parts[0], parts[1].strip()))
    return fields or None


def _fix_struct_literal_key(written: dict[str, str], error_output: str) -> dict[str, str]:
    """`return &Ledger{s: s}` against `type Ledger struct { store store.Store }`.

    The model keyed the composite literal by the CONSTRUCTOR PARAMETER's name instead
    of the FIELD's — it contradicted itself inside a single file, four lines apart. It
    earns a gate by the only criterion that counts: the compiler names the defect
    exactly, and the model still cannot repair it. In the held-out `ledger` spec the
    identical error came back on the identical line in fix round 2 and again in round 3.

    The repair is the one the compiler leaves open: rename the KEY, never touch the
    declaration. Fires only when the target is unambiguous — the struct has exactly one
    field, or exactly one field whose type matches the declared type of the value being
    assigned (read off the enclosing func's parameter list). Anything else is left for
    the model. In-place: one line, same count.
    """
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    for m in _STRUCT_LIT_KEY_RE.finditer(error_output):
        path = resolve(m.group(1))
        if not path:
            continue
        lineno, bad, typename = int(m.group(2)), m.group(3), m.group(4)
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        line = lines[lineno - 1]
        key_re = re.compile(rf"\b{re.escape(bad)}(\s*):")
        if not key_re.search(line):
            continue  # the compiler's line and the source disagree — leave it
        fields = _struct_fields(typename, written)
        if not fields:
            continue

        target: str | None = None
        if len(fields) == 1:
            target = fields[0][0]
        else:
            # Several fields: only a type match is safe. Read the value's type off the
            # enclosing func signature — `func NewLedger(s store.Store) *Ledger`.
            val = re.search(rf"\b{re.escape(bad)}\s*:\s*(\w+)\b", line)
            if val:
                sig = None
                for i in range(lineno - 1, -1, -1):
                    if lines[i].startswith("func "):
                        sig = lines[i]
                        break
                if sig:
                    p = re.search(rf"\b{re.escape(val.group(1))}\s+([\w.*\[\]]+)\s*[,)]", sig)
                    if p:
                        hits = [n for n, t in fields if t == p.group(1)]
                        if len(hits) == 1:
                            target = hits[0]

        if not target or target == bad:
            continue
        lines[lineno - 1] = key_re.sub(rf"{target}\1:", line, count=1)
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
    return changed


def _fix_atomic_inc(written: dict[str, str], error_output: str) -> dict[str, str]:
    """Rewrite `x.Inc()` -> `x.Add(1)` (and `x.Dec()` -> `x.Add(-1)`) on an atomic
    integer, ONLY on the line the compiler named. In-place: one line, same count."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    for m in _ATOMIC_INC_RE.finditer(error_output):
        path = resolve(m.group(1))
        if not path:
            continue
        lineno, recv, meth = int(m.group(2)), m.group(4), m.group(5)
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        call = f"{recv}.{meth}()"
        if call not in lines[lineno - 1]:
            continue  # the compiler's line and the source disagree — leave it
        delta = "1" if meth == "Inc" else "-1"
        lines[lineno - 1] = lines[lineno - 1].replace(call, f"{recv}.Add({delta})")
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
    return changed


def _fix_unused_var(written: dict[str, str], error_output: str) -> dict[str, str]:
    """Blank a `declared and not used` name on a multi-value `:=` short decl
    (the captured-extra-return-value pattern), only when another real new
    variable remains on the LHS so `:=` stays valid. Lone unused vars are left
    for the model. Line numbers are preserved."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    touched: set[str] = set()
    for m in _UNUSED_VAR_RE.finditer(error_output):
        path = resolve(m.group(1))
        if not path:
            continue
        lineno, name = int(m.group(2)), m.group(4)
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        line = lines[lineno - 1]
        assign = line.find(":=")
        if assign == -1:
            continue  # var-decl or other form — leave to the model
        lhs, rhs = line[:assign], line[assign:]
        new_lhs, n = re.subn(rf"\b{re.escape(name)}\b", "_", lhs, count=1)
        if n == 0:
            continue  # name not on this LHS — don't guess
        slots = [tok.strip() for tok in new_lhs.split(",") if tok.strip()]
        if any(tok != "_" for tok in slots):
            # A real new variable remains, so `:=` is still valid.
            lines[lineno - 1] = new_lhs + rhs
        elif len(slots) > 1:
            # Every slot is blank now. `_, _ := f()` declares nothing and is not
            # valid Go — but `_, _ = f()` is, and it keeps the call. This is the
            # `cfg, _ := config.Load()` the model invents and never uses: the
            # statement ALREADY threw one of the two values away, so throwing
            # away the other masks nothing that was not already discarded.
            # workapi died here — on a config.Load() its spec never asked for —
            # after six fix rounds failed to talk the model out of it.
            lines[lineno - 1] = new_lhs + rhs.replace(":=", "=", 1)
        else:
            # A LONE `cfg := f()`. Blanking it would hide a real mistake: the
            # value was computed and forgotten, and only the model knows whether
            # it meant to use it. Leave it.
            continue
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
        touched.add(path)
    return {p: changed[p] for p in touched}


# `rec.Header.Get undefined (type func() http.Header has no field or method Get)`
# — the code accessed a field/method on a METHOD VALUE without calling it.
# httptest.ResponseRecorder.Header is a METHOD (unlike http.Request.Header, a
# field), so `rec.Header.Get(...)` must be `rec.Header().Get(...)`. The compiler
# pinpoints the full expression and the trailing selector; insert the `()`.
_UNCALLED_METHOD_RE = re.compile(
    r"([\w./-]+\.go):(\d+):(\d+): ([\w.]+) undefined "
    r"\(type func\(\).*? has no field or method (\w+)\)"
)


def _fix_uncalled_method_value(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """Insert the missing `()` after a method value accessed as if it were a
    struct field, e.g. `rec.Header.Get(...)` -> `rec.Header().Get(...)`. Only the
    exact compiler-flagged expression on the flagged line is rewritten; the
    method value that DOESN'T call is unambiguous from the diagnostic, so a
    sibling `req.Header.Get` (Header is a field there) is never touched."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    touched: set[str] = set()
    for m in _UNCALLED_METHOD_RE.finditer(error_output):
        path = resolve(m.group(1))
        if not path:
            continue
        lineno, expr, meth = int(m.group(2)), m.group(4), m.group(5)
        suffix = "." + meth
        if not expr.endswith(suffix):
            continue
        base = expr[: -len(suffix)]  # `rec.Header`
        repl = base + "()." + meth  # `rec.Header().Get`
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines) or expr not in lines[lineno - 1]:
            continue
        lines[lineno - 1] = lines[lineno - 1].replace(expr, repl, 1)
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
        touched.add(path)
    return {p: changed[p] for p in touched}


# `undefined: err` where the flagged line assigns to it with plain `=` — the
# model copied a sibling closure's assignment form into a scope where the name
# was never declared. The compiler pinpoints file:line:col.
_UNDEF_LINE_RE = re.compile(r"([\w./-]+\.go):(\d+):(\d+): undefined: (\w+)(?!\s*\.)")


def _fix_undefined_assignment(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """Promote ``=`` to ``:=`` when the compiler says an LHS name is undefined
    (``_, err = s.Get(...)`` inside a fresh ``t.Run`` closure). Safe by
    construction: the compiler just proved the name is new in this scope, so
    ``:=`` is always legal, and the gate only fires when EVERY comma-separated
    LHS item is a plain identifier or ``_`` (a selector like ``x.f`` on the
    left means the line is not a short-var-decl candidate and is left alone)."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    for m in _UNDEF_LINE_RE.finditer(error_output):
        path, lineno, name = resolve(m.group(1)), int(m.group(2)), m.group(4)
        if not path:
            continue
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        line = lines[lineno - 1]
        em = re.search(r"(?<![:=!<>+\-*/%&|^])=(?!=)", line)
        if not em or '"' in line[: em.start()]:
            continue  # no plain assignment, or a string literal muddies the LHS
        lhs = line[: em.start()].strip()
        for kw in ("if ", "for "):
            if lhs.startswith(kw):
                lhs = lhs[len(kw):]
        names = [n.strip() for n in lhs.split(",")]
        if name not in names or not all(
            re.fullmatch(r"[A-Za-z_]\w*", n) for n in names
        ):
            continue
        lines[lineno - 1] = line[: em.start()] + ":" + line[em.start():]
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
    return changed


# `err, _ := svc.Create(...)` where Create returns (T, error) — the model
# captured the pair in the wrong order, so `err` holds the T and the real error
# is discarded. The compiler pinpoints the nil-comparison that unmasks it.
_SWAPPED_ERR_RE = re.compile(
    r"([\w./-]+\.go):(\d+):\d+: invalid operation: (\w+) [!=]= nil "
    r"\(mismatched types [\w.\[\]*]+ and untyped nil\)"
)


def _fix_swapped_error_assignment(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """Swap a two-element assignment whose flagged variable landed on the
    non-error slot: ``err, _ := f(...)`` -> ``_, err := f(...)``. Go convention
    puts the error LAST in a multi-return, so when the compiler proves the
    variable compared to nil has a non-error struct type, the order — not the
    call — is the bug. Only fires when the LHS is exactly the flagged name and
    a blank, so nothing referenced elsewhere can break."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    for m in _SWAPPED_ERR_RE.finditer(error_output):
        path, lineno, name = resolve(m.group(1)), int(m.group(2)), m.group(3)
        if not path:
            continue
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        line = lines[lineno - 1]
        new = re.sub(
            rf"(?<![\w.]){re.escape(name)}\s*,\s*_\s*(:?=)(?!=)",
            rf"_, {name} \1",
            line,
        )
        if new == line:
            continue
        lines[lineno - 1] = new
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
    return changed


# `mux.HandleFunc(path, authWrap(handler))` — a wrapped http.Handler passed
# where HandleFunc wants the bare func, or the reverse. The receiver method is
# simply wrong for the value; the compiler names line and receiver.
_HANDLEFUNC_RE = re.compile(
    r"([\w./-]+\.go):(\d+):\d+: cannot use .*\(value of interface type "
    r"http\.Handler\) as func\(http\.ResponseWriter, \*http\.Request\) value "
    r"in argument to (\w+)\.HandleFunc"
)
_HANDLE_RE = re.compile(
    r"([\w./-]+\.go):(\d+):\d+: cannot use .*\(value of type "
    r"func\(http\.ResponseWriter, \*http\.Request\)\) as http\.Handler value "
    r"in argument to (\w+)\.Handle\b"
)


def _fix_handle_vs_handlefunc(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """Swap ``HandleFunc`` <-> ``Handle`` on the flagged line to match the
    value actually passed: a middleware-wrapped route is an http.Handler and
    registers with Handle; a bare handler func registers with HandleFunc. Both
    directions, both compiler-pinpointed."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    def swap(regex: re.Pattern, old: str, new: str) -> None:
        for m in regex.finditer(error_output):
            path, lineno, recv = resolve(m.group(1)), int(m.group(2)), m.group(3)
            if not path:
                continue
            code = changed.get(path, written[path])
            lines = code.splitlines()
            if lineno > len(lines):
                continue
            line = lines[lineno - 1]
            fixed = line.replace(f"{recv}.{old}(", f"{recv}.{new}(", 1)
            if fixed == line:
                continue
            lines[lineno - 1] = fixed
            changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")

    swap(_HANDLEFUNC_RE, "HandleFunc", "Handle")
    swap(_HANDLE_RE, "Handle", "HandleFunc")
    return changed


# `import "module/internal/middleware"` where no such directory exists — the
# model hallucinated a local package for symbols that live in a REAL project
# package (often its own). The toolchain names both the importer and the path.
_PHANTOM_PKG_RE = re.compile(
    r"([\w./-]+\.go):\d+:\d+: no required module provides package ([\w./-]+)"
)


def _fix_phantom_local_import(
    written: dict[str, str], error_output: str, module: str | None
) -> dict[str, str]:
    """Rewrite an import of a non-existent LOCAL package to wherever its used
    symbols actually live: if the importing file's OWN package declares every
    ``phantom.Sym`` used, drop the qualifier and the import (same-package
    call); if exactly one OTHER project package exports them all, rewrite the
    import path and the qualifier to that package. Anything ambiguous is left
    for the model."""
    if not module:
        return {}
    changed: dict[str, str] = {}
    dirs = {_dir_of(p) for p in written}
    for m in _PHANTOM_PKG_RE.finditer(error_output):
        path, pkg_path = m.group(1).lstrip("./"), m.group(2)
        if not pkg_path.startswith(module + "/"):
            continue  # a real third-party module — the stdlib-swap rule's job
        rel_dir = pkg_path[len(module) + 1:]
        if rel_dir in dirs:
            continue  # the package exists; this is a go.mod problem, not ours
        if path not in written:
            cand = [p for p in written if p.endswith(path)]
            if len(cand) != 1:
                continue
            path = cand[0]
        code = changed.get(path, written[path])
        phantom = rel_dir.rsplit("/", 1)[-1]
        syms = set(re.findall(rf"\b{re.escape(phantom)}\.(\w+)", code))
        if not syms:
            continue
        drop_import = re.compile(
            rf'^\s*(?:\w+\s+)?"{re.escape(pkg_path)}"\s*\n', re.MULTILINE
        )

        # The most natural version of this mistake: the model puts the MODULE PATH
        # in front of a STANDARD LIBRARY package —
        # "guildlm.dev/workapi/internal/slog" for "log/slog". The symbols
        # (slog.New, slog.NewTextHandler) live in no project package at all, so
        # the owner search below finds nothing and gives up. But the phantom's
        # last segment names a stdlib package, and the import path is simply the
        # real one with a module glued to its front — so put the real one back.
        stdlib = next(
            (c for c in _STDLIB_IMPORTABLE if c.rsplit("/", 1)[-1] == phantom), None
        )
        if stdlib:
            changed[path] = drop_import.sub(f'\t"{stdlib}"\n', code, count=1)
            _log(f"  {path}: {pkg_path} is the standard library's {stdlib} with the "
                 f"module path glued on — importing the real one")
            continue
        # own package first: same-dir siblings may declare the symbols
        # unexported, and the fix is simply an unqualified call
        own_dir = _dir_of(path)
        own_decls: set[str] = set()
        for p, c in written.items():
            if p != path and _dir_of(p) == own_dir:
                own_decls |= top_level_decls(c) | method_decls(c)
        if syms <= own_decls:
            new = drop_import.sub("", code)
            new = re.sub(rf"\b{re.escape(phantom)}\.(\w+)", r"\1", new)
            changed[path] = new
            continue
        # otherwise: exactly one project package exporting every used symbol
        owners: list[tuple[str, str]] = []  # (pkg_name, dir)
        by_dir: dict[str, set[str]] = {}
        pkg_of_dir: dict[str, str] = {}
        for p, c in written.items():
            d = _dir_of(p)
            if d == own_dir or not p.endswith(".go"):
                continue
            by_dir.setdefault(d, set()).update(
                n for n in top_level_decls(c) if n[:1].isupper()
            )
            pkg_of_dir.setdefault(d, pkg_name_of(c))
        for d, exported in by_dir.items():
            if syms <= exported and pkg_of_dir.get(d) != "main":
                owners.append((pkg_of_dir[d], d))
        if len(owners) != 1:
            continue
        owner_pkg, owner_dir = owners[0]
        new = drop_import.sub("", code)
        new = re.sub(
            rf"\b{re.escape(phantom)}\.(\w+)", rf"{owner_pkg}.\1", new
        )
        changed[path] = _ensure_import(new, f"{module}/{owner_dir}")
    return changed


# A test that guards a slice length with t.Errorf and then indexes anyway:
# Errorf CONTINUES, so `X[0]` on an empty slice panics and takes the whole
# package's test binary down with it. The panic trace pinpoints the line.
_OOR_PANIC_RE = re.compile(r"panic: runtime error: index out of range")
_TEST_FRAME_RE = re.compile(r"([\w./-]+_test\.go):(\d+)")


def _fix_fatal_guard(written: dict[str, str], error_output: str) -> dict[str, str]:
    """Promote the ``t.Errorf`` guarding a ``len(...)`` check to ``t.Fatalf``
    when an index-out-of-range panic points just past it. Errorf-then-index is
    the mechanical half of the bug (the wrong-assertion half stays with the
    model): failing FAST turns an opaque panic into a plain assertion failure
    the fix loop can reason about."""
    if not _OOR_PANIC_RE.search(error_output):
        return {}

    def resolve(path: str) -> str | None:
        # panic traces print ABSOLUTE paths, so match the project-relative
        # key as a suffix of the frame path (the reverse of compiler output)
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if path.endswith(p)]
        return max(cand, key=len) if cand else None

    changed: dict[str, str] = {}
    for m in _TEST_FRAME_RE.finditer(error_output):
        path, lineno = resolve(m.group(1)), int(m.group(2))
        if not path:
            continue
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        # scan upward from the panicking line for the nearest Errorf that sits
        # under a len(...) condition — that guard should have been fatal
        for i in range(lineno - 1, max(lineno - 8, 0) - 1, -1):
            if "t.Errorf(" not in lines[i - 1]:
                continue
            window = "\n".join(lines[max(i - 4, 0):i])
            if "len(" not in window:
                continue
            lines[i - 1] = lines[i - 1].replace("t.Errorf(", "t.Fatalf(", 1)
            changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
            break
    return changed


# `if got, want := x, models.Task{...}; got != want {` — a composite literal in
# an if/for/switch header must be parenthesized; the parser even hints at it.
_IFLIT_RE = re.compile(
    r"([\w./-]+\.go):\d+:\d+: expected boolean expression, found assignment"
    r".*missing parentheses around composite literal"
)
# A named-type composite literal: `T{` or `pkg.T{` (capitalized type name, so a
# block-open like `want {` never matches).
_COMPLIT_RE = re.compile(r"(?<![\w.()])((?:[a-z_]\w*\.)?[A-Z]\w*)\s*\{")


def _fix_if_composite_literal(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """Wrap named-type composite literals in parentheses on every if/for/switch
    header line of a file the parser flagged with the missing-parentheses hint.
    Redundant parens are valid Go, so over-wrapping is harmless; fixing the
    whole file at once avoids paying one round per occurrence (a syntax error
    masks every later diagnostic in the package)."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    def wrap_literals(line: str) -> str:
        out, pos = "", 0
        while True:
            m = _COMPLIT_RE.search(line, pos)
            if not m:
                return out + line[pos:]
            # balanced-brace scan from the literal's `{`
            depth, j = 1, line.index("{", m.start()) + 1
            while j < len(line) and depth:
                depth += (line[j] == "{") - (line[j] == "}")
                j += 1
            if depth:  # runs past the line (multi-line literal) — leave it
                return out + line[pos:]
            out += line[pos:m.start()] + "(" + line[m.start():j] + ")"
            pos = j

    for m in _IFLIT_RE.finditer(error_output):
        path = resolve(m.group(1))
        if not path or path in changed:
            continue
        code = written[path]
        lines = code.splitlines()
        new_lines = [
            wrap_literals(l)
            if l.lstrip().startswith(("if ", "for ", "switch ")) else l
            for l in lines
        ]
        if new_lines != lines:
            changed[path] = "\n".join(new_lines) + (
                "\n" if code.endswith("\n") else ""
            )
    return changed


_HANDLERFUNC_RE = re.compile(
    r"([\w./-]+\.go):(\d+):(\d+): cannot use ([\w.]+)"
    r" \(value of type func\([^)]*\bResponseWriter\b[^)]*\)\)"
    r" as http\.Handler value"
    r".*missing method ServeHTTP"
)


def _fix_handlerfunc_wrap(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """``cannot use X (value of type func(...ResponseWriter...)) as
    http.Handler value ... missing method ServeHTTP`` — the model passed a
    handler-SHAPED func where the http.Handler interface is expected. The
    idiomatic repair is always the same one-token wrap, yet the 7B burns whole
    fix rounds resampling around it: rewrite the use site to
    ``http.HandlerFunc(X)``. Only a func whose reported type mentions
    ResponseWriter is touched (a non-handler func mismatch is a real bug for
    the model); goimports on write supplies net/http if missing."""
    changed: dict[str, str] = {}
    for m in _HANDLERFUNC_RE.finditer(error_output):
        path, lineno, col, name = (
            m.group(1).lstrip("./"), int(m.group(2)), int(m.group(3)), m.group(4),
        )
        if path not in written:
            cand = [p for p in written if p.endswith(path)]
            if len(cand) != 1:
                continue
            path = cand[0]
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        line = lines[lineno - 1]
        # the identifier as a VALUE (not a call), preferring the reported column
        pattern = re.compile(rf"(?<![\w.)]){re.escape(name)}\b(?!\s*\()")
        start = col - 1 if 0 <= col - 1 < len(line) else 0
        mm = pattern.search(line, start) or pattern.search(line)
        if not mm:
            continue
        if line[:mm.start()].endswith("http.HandlerFunc("):
            continue  # already wrapped (stale diagnostic)
        lines[lineno - 1] = (
            line[:mm.start()] + f"http.HandlerFunc({name})" + line[mm.end():]
        )
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
    return changed


# `not enough arguments in call to Recover\n\thave (*slog.Logger)\n\twant
# (http.Handler, *slog.Logger)` — the model defined a middleware constructor
# with the next handler as its FIRST parameter (func Recover(next http.Handler,
# log *slog.Logger) http.Handler) yet calls it as Recover(log) and hands it to a
# Chain(h, ...Middleware) whose Middleware is `func(http.Handler) http.Handler`.
# It adopted the canonical CALL shape (from retrieval) but not the DEFINITION
# shape. The fix is a single definition-site rewrite to config-in/Middleware-out,
# which resolves BOTH the arity error and the interface mismatch at once.
_MW_ARITY_RE = re.compile(
    r"not enough arguments in call to (\w+)\n\s*have \([^)]*\)\n\s*want \(http\.Handler,"
)


def _rewrite_middleware_def(code: str, name: str) -> str:
    """Rewrite ``func name(next http.Handler, <cfg...>) http.Handler { BODY }`` to
    ``func name(<cfg...>) Middleware { return func(next http.Handler) http.Handler
    { BODY } }``. Safe by construction: bails to the unchanged source on ANY
    ambiguity (name not a top-level def, unbalanced parens/braces, first param not
    ``<ident> http.Handler``, no trailing config param, or return type not
    http.Handler) — worst case a no-op that leaves the residual for the model.
    Indentation is left to gofmt-on-write; only tokens and brace balance matter."""
    m = re.search(rf"(?m)^func {re.escape(name)}\(", code)
    if not m:
        return code
    sig_start, paren_open = m.start(), m.end() - 1
    depth, i = 0, paren_open
    while i < len(code):
        depth += (code[i] == "(") - (code[i] == ")")
        if depth == 0:
            break
        i += 1
    else:
        return code
    paren_close = i
    rm = re.match(r"\s*http\.Handler\s*\{", code[paren_close + 1:])
    if not rm:
        return code
    body_open = paren_close + 1 + rm.end() - 1
    depth, j = 0, body_open
    while j < len(code):
        depth += (code[j] == "{") - (code[j] == "}")
        if depth == 0:
            break
        j += 1
    else:
        return code
    body_close = j
    params = _split_top_level_args(code[paren_open + 1:paren_close])
    if len(params) < 2:
        return code
    fm = re.match(r"(\w+)\s+http\.Handler$", params[0].strip())
    if not fm:
        return code
    next_name = fm.group(1)
    cfg = ", ".join(p.strip() for p in params[1:])
    body = code[body_open + 1:body_close]
    new_def = (
        f"func {name}({cfg}) Middleware {{\n"
        f"\treturn func({next_name} http.Handler) http.Handler {{{body}}}\n"
        f"}}"
    )
    return code[:sig_start] + new_def + code[body_close + 1:]


def _fix_middleware_arity(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """Repair middleware constructors defined with the next handler as a parameter
    so they match the ``Middleware = func(http.Handler) http.Handler`` type their
    own Chain expects (see _rewrite_middleware_def). Only files that actually
    declare that Middleware shape are considered, so a genuine two-arg http.Handler
    helper elsewhere is never touched."""
    names = {m.group(1) for m in _MW_ARITY_RE.finditer(error_output)}
    if not names:
        return {}
    changed: dict[str, str] = {}
    for path, code in written.items():
        if not path.endswith(".go") or "func(http.Handler) http.Handler" not in code:
            continue
        new_code = code
        for name in names:
            new_code = _rewrite_middleware_def(new_code, name)
        if new_code != code:
            changed[path] = new_code
    return changed


def _interface_body_span(code: str, typ: str) -> tuple[int, int] | None:
    """Byte span (open-brace idx, close-brace idx) of ``type typ interface { ... }``
    in ``code``, or None if ``typ`` is not declared as an interface (it may be a
    struct, an alias, or absent). Brace-matched so nested func/struct types in
    method signatures don't confuse the scan."""
    m = re.search(rf"(?m)^type\s+{re.escape(typ)}\s+interface\s*\{{", code)
    if not m:
        return None
    open_brace = m.end() - 1
    depth = 0
    for i in range(open_brace, len(code)):
        depth += (code[i] == "{") - (code[i] == "}")
        if depth == 0:
            return (open_brace, i)
    return None


def _interface_method_names(body: str) -> set[str]:
    """Method names declared directly in an interface body (``Name(`` lines).
    Embedded interfaces (``io.Reader``) and comments are ignored."""
    names: set[str] = set()
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        m = re.match(r"(\w+)\s*\(", s)
        if m:
            names.add(m.group(1))
    return names


def _lift_method_signature(code: str, recv_type: str, meth: str) -> str | None:
    """Extract ``meth(params) results`` from a concrete method
    ``func (r *recv_type) meth(params) results { ... }`` in ``code``, ready to
    paste into an interface. Verbatim — no type inference. Returns None if the
    method isn't found, the parens/brace don't balance, or the result type is
    exotic (contains a nested struct/interface/func literal), which is left to the
    model rather than guessed."""
    pat = re.compile(
        rf"func\s*\(\s*(?:\w+\s+)?\*?{re.escape(recv_type)}\b(?:\[[^\]]*\])?\s*\)"
        rf"\s*{re.escape(meth)}\s*\("
    )
    m = pat.search(code)
    if not m:
        return None
    paren_open = m.end() - 1
    depth = 0
    paren_close = -1
    for i in range(paren_open, len(code)):
        depth += (code[i] == "(") - (code[i] == ")")
        if depth == 0:
            paren_close = i
            break
    if paren_close == -1:
        return None
    params = code[paren_open + 1:paren_close]
    rest = code[paren_close + 1:]
    brace = rest.find("{")
    if brace == -1:
        return None
    results = rest[:brace].strip()
    # Bail on results we can't safely transcribe onto one interface line.
    if any(kw in results for kw in ("struct", "interface", "func")) \
            or results.count("(") != results.count(")"):
        return None
    if "{" in params or "}" in params:  # inline func-typed param body -> too rich
        return None
    sig = f"{meth}({params})"
    if results:
        sig += f" {results}"
    return sig


def _fix_interface_missing_method(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """Deterministic repair for the taskflow class: the compiler reports
    ``type Store has no field or method Update`` at a call through an interface,
    because the model wrote the method on the concrete implementation but forgot
    to DECLARE it on the interface. When a concrete type in the SAME package
    already implements every method the interface currently declares AND also has
    the missing method, lift that method's exact signature into the interface.

    Safe by construction. The chosen implementer provably satisfies the augmented
    interface (it already has all current methods plus the added one), the
    signature is copied verbatim from real code (no inference), and the gate fires
    only within one package so type qualification can't drift. It BAILS on every
    ambiguity: the type isn't an interface (a struct-missing-method is a different
    bug), the method is already declared, no same-package type implements the
    interface-plus-method, or candidate implementers disagree on the signature.
    In particular it does nothing when the method is missing from BOTH sides
    (there is no signature to lift) — that completeness case is left to the model.
    """
    pairs = {(m.group(1), m.group(2)) for m in _NOMETHOD_RE.finditer(error_output)}
    if not pairs:
        return {}
    changed: dict[str, str] = {}
    for typ, meth in pairs:
        # Locate the interface declaration among non-test source files.
        iface_path: str | None = None
        span: tuple[int, int] | None = None
        for p, c in written.items():
            if not p.endswith(".go") or p.endswith("_test.go"):
                continue
            span = _interface_body_span(changed.get(p, c), typ)
            if span:
                iface_path = p
                break
        if iface_path is None or span is None:
            continue
        src = changed.get(iface_path, written[iface_path])
        open_b, close_b = span
        iface_methods = _interface_method_names(src[open_b + 1:close_b])
        if meth in iface_methods:
            continue  # the interface already has it; the miss is elsewhere

        # Concrete types and their method names in the interface's package.
        iface_dir = _dir_of(iface_path)
        pkg_files = {
            p: changed.get(p, c) for p, c in written.items()
            if p.endswith(".go") and not p.endswith("_test.go")
            and _dir_of(p) == iface_dir
        }
        methods_by_type: dict[str, set[str]] = {}
        for c in pkg_files.values():
            for recv, name in _METHOD_DECL_RE.findall(c):
                methods_by_type.setdefault(recv, set()).add(name)
        candidates = [
            t for t, ms in methods_by_type.items()
            if t != typ and meth in ms and iface_methods <= ms
        ]
        if not candidates:
            continue  # nobody implements iface+meth here (e.g. Case B) -> leave it

        # A single agreed signature across candidates, or bail.
        sigs: set[str] = set()
        for t in candidates:
            for c in pkg_files.values():
                sig = _lift_method_signature(c, t, meth)
                if sig:
                    sigs.add(sig)
                    break
        if len(sigs) != 1:
            continue
        sig = next(iter(sigs))

        head = src[:close_b].rstrip()
        new_src = f"{head}\n\t{sig}\n" + src[close_b:]
        changed[iface_path] = new_src
        _log(f"  added missing method {meth} to interface {typ} "
             f"(lifted from its implementation)")
    return changed


_PTR_IFACE_RE = re.compile(r"type \*(\w+) is pointer to interface, not interface")


# `cannot use NewRouter(s) (value of interface type http.Handler) as *http.ServeMux
# value in return statement: need type assertion`
_MUX_RETURN_RE = re.compile(
    r"([\w./-]+\.go):(\d+):(\d+): cannot use [^\n]*?\(value of interface type "
    r"http\.Handler\) as \*http\.ServeMux value in return statement"
)
# `func newRouter() *http.ServeMux {`
_MUX_SIG_RE = re.compile(r"^(func\s+\w+\([^)]*\)\s+)\*http\.ServeMux(\s*\{)", re.M)


def _fix_mux_return_type(written: dict[str, str], error_output: str) -> dict[str, str]:
    """A test helper declared as `func newRouter() *http.ServeMux` returning
    NewRouter(...), which is middleware-wrapped and therefore an http.Handler.

    The router is a mux right up until Chain wraps it, and then it is not one any
    more — so the model's guess is the reasonable one, and it is wrong. Seen in two
    independent specs, and the model could not repair it when told: three fix rounds
    in taskflow all rewrote the same signature back.

    The repair is the only one the compiler leaves open: widen the RETURN TYPE to
    http.Handler, and drop the `.(*http.ServeMux)` assertion if one is there. Tests
    only ever call h.ServeHTTP, which http.Handler already provides — nothing needs
    the mux. Line-preserving: both edits stay on their own line.

    Fires ONLY on the file the compiler named, and only on a signature that really
    does return *http.ServeMux. A helper that legitimately needs the mux cannot be
    the subject of this error — the compiler is telling us it cannot have one.
    """
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    for m in _MUX_RETURN_RE.finditer(error_output):
        path = resolve(m.group(1))
        if not path:
            continue
        code = changed.get(path, written[path])
        new = _MUX_SIG_RE.sub(r"\1http.Handler\2", code)
        new = new.replace(".(*http.ServeMux)", "")
        if new != code:
            changed[path] = new
    return changed


def _fix_pointer_to_interface(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """``h.store.CreateTask undefined (type *Store is pointer to interface, not
    interface)`` — the model declared a field or parameter as ``*Store`` (a
    POINTER to an interface), which has no methods, so every call through it is
    undefined. A pointer to an interface is essentially always a bug in Go: an
    interface value is already a reference. The fix is to drop the star and hold
    the interface by value.

    Rewrites ``*T`` -> ``T`` (collapsing any run of leading stars) wherever the
    compiler named ``*T`` as a pointer-to-interface AND the project itself
    declares ``T`` as an interface. Safe: for a capitalised interface type name a
    ``*T`` token only ever appears in a type position (a value dereference is
    ``*t`` on a lowercase variable), and every such type position — field, param,
    return, slice, map, channel — is wrong when T is an interface, so correcting
    all of them is right. A ``*Struct`` is never touched (the guard requires an
    interface), nor is a concrete ``*MemStore`` in a ``var _ T = (*MemStore)(nil)``
    assertion (different name)."""
    names = {m.group(1) for m in _PTR_IFACE_RE.finditer(error_output)}
    if not names:
        return {}
    ifaces = {
        n for n in names
        if any(
            _interface_body_span(c, n)
            for p, c in written.items()
            if p.endswith(".go") and not p.endswith("_test.go")
        )
    }
    if not ifaces:
        return {}
    changed: dict[str, str] = {}
    for path, code in written.items():
        if not path.endswith(".go"):
            continue
        new_code = code
        for n in ifaces:
            new_code = re.sub(rf"\*+({re.escape(n)})\b", r"\1", new_code)
        if new_code != code:
            changed[path] = new_code
    return changed


# `t.Fatalf undefined (type Task has no field or method Fatalf)` — the tester was
# shadowed. Distinguished from the plain no-method error by the receiver being
# literally `t` and the selector being a *testing.T method.
_SHADOWED_T_RE = re.compile(
    r"\bt\.(\w+) undefined \(type (\w+) has no field or method \1\)"
)

# The SAME mistake, reported completely differently. `t := models.Task{...}` in a
# function whose parameter is already `t` does not shadow anything — a parameter
# lives in the body's own scope — so Go reads it as an ASSIGNMENT to the tester
# and complains about the type instead:
#
#   cannot use models.Task{…} (value of struct type models.Task) as *testing.T
#   value in assignment
#
# `t.Fatalf` still resolves to *testing.T, so the "has no field or method" error
# never appears and the gate above never fires — even though its rewriter repairs
# the file perfectly the moment it is handed it. One regex was all that stood
# between a working gate and a spec that failed.
_TESTER_OVERWRITTEN_RE = re.compile(
    r"([\w./-]+\.go):\d+:\d+: cannot use .+ as \*testing\.T value in assignment"
)

# Methods that belong to *testing.T. A domain type declaring one of these makes
# `t.X` genuinely ambiguous inside the shadow, and the gate refuses to guess.
_TESTING_METHODS = frozenset(
    """Fatal Fatalf Error Errorf Log Logf Fail FailNow Failed Skip Skipf SkipNow
    Skipped Helper Cleanup Parallel Run TempDir Setenv Chdir Name Deadline""".split()
)

_SHADOWFIX = Path(__file__).resolve().parent.parent / "tools" / "shadowfix.go"

# Field names declared at the start of a line inside a struct body.
_FIELD_NAME_RE = re.compile(r"^\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s+\S", re.M)


def _type_members(written: dict[str, str], typ: str) -> set[str]:
    """Every method and struct field name belonging to ``typ`` across the project.
    Used only to REFUSE work: a domain type carrying a testing-shaped member (a
    ``Task.Name`` field is entirely ordinary) makes ``t.Name`` inside a shadow
    ambiguous, and an ambiguous rename is worse than none."""
    members: set[str] = set()
    for code in written.values():
        for recv, name in _METHOD_DECL_RE.findall(code):
            if recv == typ:
                members.add(name)
        span = _struct_body_span(code, typ)
        if span:
            body = code[span[0] + 1:span[1]]
            for group in _FIELD_NAME_RE.findall(body):
                members.update(n.strip() for n in group.split(","))
    return members


def _struct_body_span(code: str, typ: str) -> tuple[int, int] | None:
    """Brace-matched span of ``type <typ> struct { ... }``, or None."""
    m = re.search(rf"\btype\s+{re.escape(typ)}\b[^{{\n]*\bstruct\s*{{", code)
    if not m:
        return None
    open_b = code.index("{", m.end() - 1)
    depth = 0
    for i in range(open_b, len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return open_b, i
    return None


def _fix_shadowed_tester(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """``t.Fatalf undefined (type Task has no field or method Fatalf)`` — the
    model wrote ``for _, t := range tasks``, so the loop variable shadows the
    ``t *testing.T`` parameter and every ``t.Fatalf`` in the body now resolves to
    a Task. This is the last stochastic failure mode left in the suite, and it is
    NUDGE-RESISTANT: an explicit "never name a variable t" instruction in the
    spec did not hold across repeated rolls. A gate is the only reliable fix.

    The repair is a scope-aware rename of the SHADOW (never the tester): the
    declaration and every non-tester use of ``t`` inside the shadowed scope get a
    fresh name, while ``t.<testing method>`` is left alone so it binds to the
    un-shadowed ``*testing.T`` again::

        for _, tk := range tasks {
                if err := s.Create(tk); err != nil {   // the domain value
                        t.Fatalf("Create: %v", err)   // the tester, restored
                }
        }

    Renaming a single-letter identifier is exactly where a regex would be unsafe
    (selectors, nested closures, struct fields, inner re-shadows), so the rewrite
    runs on a real ``go/ast`` walk in ``tools/shadowfix.go`` and bails on any
    construct it cannot resolve with certainty. This gate can only ever touch a
    file the compiler has ALREADY rejected with this error, so it cannot regress
    a green file. It no-ops on anything unexpected — a missing toolchain, a
    parse error, or a domain type that itself declares a testing-shaped method
    (which would make ``t.X`` ambiguous).
    """
    hits = {(m.group(2), m.group(1)) for m in _SHADOWED_T_RE.finditer(error_output)}
    # The same mistake, reported as an assignment to the tester rather than a
    # missing method — see _TESTER_OVERWRITTEN_RE. Nothing about the repair
    # changes; only the message the compiler chose to print.
    overwritten = bool(_TESTER_OVERWRITTEN_RE.search(error_output))
    if (not hits and not overwritten) or not _SHADOWFIX.exists():
        return {}

    # Ambiguity guard: a shadowing type that declares a testing-shaped member —
    # a `Task.Name` field, an `Error()` method — makes `t.Name` inside the scope
    # readable as either the domain value or the tester. Refuse the whole file.
    for typ, _ in hits:
        if _type_members(written, typ) & _TESTING_METHODS:
            return {}

    targets = [
        p for p in _offending_files(error_output, list(written))
        if p.endswith("_test.go")
    ]
    changed: dict[str, str] = {}
    for path in targets:
        try:
            proc = subprocess.run(
                ["go", "run", str(_SHADOWFIX)],
                input=written[path],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return {}  # no toolchain, no opinion
        if proc.returncode != 0 or not proc.stdout.strip():
            continue  # exit 3 = nothing to do; anything else = stay out of it
        if proc.stdout != written[path]:
            changed[path] = proc.stdout
            _log(f"  renamed the loop variable shadowing t *testing.T in {path}")
    return changed


_FRESHREQ = Path(__file__).resolve().parent.parent / "tools" / "freshreq.go"


def _fix_drained_request(written: dict[str, str], error_output: str) -> dict[str, str]:
    """Rebuild an *http.Request that is handed to ServeHTTP more than once.

    A request Body is an io.Reader: the first ServeHTTP DRAINS it, so the second
    call sends an empty body, json.Decode fails on EOF, and the handler answers
    400 — a "POST twice -> 409" case reports `want 409, got 400` against a handler
    that is perfectly correct. The test is wrong; the product is right.

    STRUCTURAL, not error-driven, and that is deliberate. The defect surfaces as a
    test assertion failure whose text is written by the spec (`want 409, got
    400`), not by the compiler — there is no sentence a gate could key on. It is
    instead an unconditional property of the source: the same body-bearing request
    reaching ServeHTTP twice with no reassignment between is ALWAYS a drained
    body, whatever else the project is doing.

    This one earned its gate. Six escalating versions of the prompt default failed
    to stop it — the rule names the variable, forbids the reuse, explains the
    drain, predicts the exact status code, quotes the wrong code verbatim as
    "exactly the bug", and anchors the example to the duplicate test by name. The
    corpus was checked and does not teach it. The model writes it anyway, because
    the duplicate case is the ONE test in which both requests are a POST of the
    SAME body to the SAME URL — and that identity is exactly what makes reuse look
    correct. A nudge is not a gate.

    Safety lives in tools/freshreq.go: a bodyless request (GET, DELETE) can be
    legally replayed and is left alone, an already-reassigned request is left
    alone, and the rebuild REPLAYS the mutations the author applied — without
    which the repaired test loses its `req.Header.Set("Authorization", ...)` and
    fails 401 instead of 400, trading one silent breakage for another.
    """
    del error_output  # structural: the compiler has nothing to say about this
    if not _FRESHREQ.exists():
        return {}
    changed: dict[str, str] = {}
    for path, code in written.items():
        if not path.endswith("_test.go") or "ServeHTTP" not in code:
            continue
        try:
            proc = subprocess.run(
                ["go", "run", str(_FRESHREQ)],
                input=code,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return {}  # no toolchain, no opinion
        if proc.returncode != 0 or not proc.stdout.strip():
            continue  # exit 3 = nothing to do; anything else = stay out of it
        if proc.stdout != code:
            changed[path] = proc.stdout
            _log(f"  rebuilt a request that was served twice (drained body) in {path}")
    return changed


_DEADASSERT = Path(__file__).resolve().parent.parent / "tools" / "deadassert.go"


def _fix_dead_error_assertion(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """Delete the happy-path guard that makes an error-expecting assertion dead.

    In a test that EXPECTS an error, the error is the RESULT, not an obstacle. The
    model writes the `errors.Is(err, errBoom)` check the spec asked for — and then
    layers the file's dominant rhythm, `if err != nil { t.Fatalf(...) }`, ON TOP of
    it rather than INSTEAD of it. The guard fires on the very error the test exists
    to observe, and the assertion below it can never run.

    STRUCTURAL, like _fix_drained_request and for the same reason: the failure
    surfaces as `List: boom` — a message the SPEC wrote, not the compiler — so
    there is no sentence to key on. It is instead an unconditional contradiction in
    the source: a test cannot both demand that `err` be nil and assert what `err`
    wraps. Whichever way you read it, the guard is wrong.

    Nudge-resistant, which is what earns it a gate. The spec forbids it in those
    words, the fixer is now shown that purpose AND the test-authoring defaults, and
    the model still re-adds it — it obeyed at GENERATION and a FIX round put the
    guard back. Seen in taskapipro and again in workapi.

    Safety lives in tools/deadassert.go: the guard is removed ONLY when the same
    `err` is later the subject of errors.Is/As in the same block, its body is
    nothing but a single t.Fatalf/Errorf, and `err` is not reassigned in between (a
    reassignment makes the later check a DIFFERENT error, and the guard legitimate).
    A happy-path guard with no errors.Is beneath it is ordinary and is left alone.
    """
    del error_output  # structural: the compiler has nothing to say about this
    if not _DEADASSERT.exists():
        return {}
    changed: dict[str, str] = {}
    for path, code in written.items():
        if not path.endswith("_test.go") or "errors.Is" not in code:
            continue
        try:
            proc = subprocess.run(
                ["go", "run", str(_DEADASSERT)],
                input=code,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return {}  # no toolchain, no opinion
        if proc.returncode != 0 or not proc.stdout.strip():
            continue  # exit 3 = nothing to do; anything else = stay out of it
        if proc.stdout != code:
            changed[path] = proc.stdout
            _log(f"  removed a guard that made the errors.Is assertion dead in {path}")
    return changed


# `func NewStoreImpl() *StoreImpl {` — a constructor taking no arguments and
# returning a single value, which is the only shape we can safely delegate to.
_CTOR_DECL_RE = re.compile(r"^func\s+(New\w+)\(\)\s+([^\s({][^{\n]*?)\s*\{", re.M)


def _same_thing(a: str, b: str) -> bool:
    """Do two constructor suffixes name the same thing? ``Store`` and ``MemStore``
    do (one contains the other); ``Store`` and ``Cache`` do not. Empty names never
    match, so ``New`` alone relates to nothing."""
    return bool(a) and bool(b) and (a in b or b in a)


def _fix_missing_constructor_alias(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """``undefined: NewStore`` — the spec told store.go, emphatically, to expose a
    constructor named EXACTLY ``NewStore``, and the model wrote a ``Store``
    interface with a ``StoreImpl`` built by ``NewStoreImpl`` instead. Everything
    else in the project — handlers, main — is internally consistent with the name
    the model chose; only the callers the spec pinned to ``NewStore`` (the tests)
    fail to compile.

    This prior is immovable. Across repeated rolls the model wrote
    ``StoreImpl``/``NewStoreImpl`` every single time, and it kept writing it even
    when store.go was regenerated with ``undefined: NewStore`` in the fix prompt.
    A spec cannot argue a 7B out of an idiom it is this sure about — which is the
    whole reason gates exist.

    The repair is provable rather than persuasive: when exactly one zero-argument
    constructor in the package builds the same thing under a different name,
    append an alias that delegates to it::

        func NewStore() *MemStore { return NewMemStore() }

    It compiles by construction — the delegate exists, takes nothing and returns
    one value — and the returned type satisfies whatever interface the project
    declared, because that is the type the model built everything else around.

    "The same thing" is checked by name, in either direction: the missing
    ``NewStore`` names a ``Store`` and ``NewMemStore``/``NewStoreImpl`` contain
    it, while a call to the missing ``NewMemStore`` in a package that declares
    ``NewStore`` names something the declared constructor already builds. Both
    directions happen — the model picks the abstract name in one file and the
    concrete one in another — and either way exactly one constructor exists to
    delegate to. A lone ``NewCache`` is related to neither and is never mistaken
    for the store. Bails on any ambiguity: several candidates, a candidate that
    takes arguments or returns a tuple, or a name that is already declared."""
    declared: set[str] = set()
    for p, c in written.items():
        if p.endswith(".go"):
            declared |= top_level_decls(c)
    missing = {
        m.group(2) for m in _UNDEF_BARE_RE.finditer(error_output)
        if m.group(2).startswith("New") and m.group(2) not in declared
    }
    changed: dict[str, str] = {}
    for name in missing:
        thing = name[len("New"):]  # NewStore -> Store
        if not thing:
            continue
        candidates = [
            (p, ctor, ret)
            for p, c in written.items()
            if p.endswith(".go") and not p.endswith("_test.go")
            for ctor, ret in _CTOR_DECL_RE.findall(changed.get(p, c))
            if ctor != name and _same_thing(thing, ctor[len("New"):])
        ]
        if len(candidates) != 1:
            continue  # nobody to delegate to, or no way to choose — leave it
        path, ctor, ret = candidates[0]
        src = changed.get(path, written[path])
        changed[path] = (
            src.rstrip("\n")
            + f"\n\n// {name} is the constructor name the rest of the project was\n"
            f"// specified to call; it delegates to the one declared above.\n"
            f"func {name}() {ret} {{ return {ctor}() }}\n"
        )
        _log(f"  added the specified constructor {name} in {path}, "
             f"delegating to {ctor}")
    return changed


# `./h_test.go:11:47: cannot use NewMemStore() (value of interface type Store) as
# *API value in argument to NewRouter`
_ARG_TYPE_RE = re.compile(
    r"([\w./-]+\.go):(\d+):(\d+): cannot use .+? "
    r"\((?:value|variable) of (?:interface )?type ([\w.*\[\]]+)\) "
    r"as ([\w.*\[\]]+) value in argument to (\w+)"
)

# `func NewAPI(store Store) *API {` — a one-argument adapter.
_ADAPTER_DECL_RE = re.compile(
    r"^func\s+(\w+)\(\s*\w+\s+([\w.*\[\]]+)\s*\)\s+([\w.*\[\]]+)\s*\{", re.M
)

_WRAPARG = Path(__file__).resolve().parent.parent / "tools" / "wraparg.go"


def _fix_argument_type_adapter(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """``cannot use NewMemStore() (value of interface type Store) as *API value in
    argument to NewRouter`` — the model wired the router straight to the store and
    skipped the layer in between, even though the spec spells the composition out
    as ``NewRouter(NewAPI(NewStore()))``.

    The repair is provable when the project declares EXACTLY ONE function that
    turns what you have into what is wanted — here ``func NewAPI(store Store)
    *API`` is the only Store-to-*API there is, so the composition the model meant
    is not in doubt::

        NewRouter(NewMemStore())  ->  NewRouter(NewAPI(NewMemStore()))

    Uniqueness is proved here, before the rewrite runs; the rewrite itself is an
    AST edit at the exact position the compiler named (``tools/wraparg.go``),
    because the argument can be any expression and the same call may appear
    several times in one file. Bails whenever the adapter is not unique, or does
    not exist, or the argument is already wrapped in it."""
    hits = list(_ARG_TYPE_RE.finditer(error_output))
    if not hits or not _WRAPARG.exists():
        return {}
    changed: dict[str, str] = {}
    for m in hits:
        path_hint, line, col, have, want, _callee = (
            m.group(1), int(m.group(2)), int(m.group(3)),
            m.group(4), m.group(5), m.group(6),
        )
        target = next(
            (p for p in written if os.path.basename(p) == os.path.basename(path_hint)),
            None,
        )
        if target is None:
            continue
        adapters = {
            fn
            for p, c in written.items()
            if p.endswith(".go") and not p.endswith("_test.go")
            for fn, param, ret in _ADAPTER_DECL_RE.findall(c)
            if param == have and ret == want
        }
        if len(adapters) != 1:
            continue  # no unique way to get from `have` to `want` — do not guess
        adapter = next(iter(adapters))
        try:
            proc = subprocess.run(
                ["go", "run", str(_WRAPARG), str(line), str(col), adapter],
                input=changed.get(target, written[target]),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if proc.returncode != 0 or not proc.stdout.strip():
            continue
        changed[target] = proc.stdout
        _log(f"  wrapped the argument to {_callee} in {adapter} in {target} "
             f"({have} -> {want})")
    return changed


# Same error shape as the adapter gate, but with the CALLED function captured:
# `cannot use Logging(logger) (value of interface type http.Handler) as
# Middleware value in argument to Chain`
_CALLED_ARG_RE = re.compile(
    r"([\w./-]+\.go):(\d+):(\d+): cannot use (\w+)\([^)]*\) "
    r"\((?:value|variable) of (?:interface )?type ([\w.*\[\]]+)\) "
    r"as ([\w.*\[\]]+) value in argument to (\w+)"
)

# `type Middleware func(http.Handler) http.Handler`
_FUNC_TYPE_DECL_RE = re.compile(
    r"^type\s+(\w+)\s+func\(([^)]*)\)\s*([\w.*\[\]]*)\s*$", re.M
)

# `func Logging(next http.Handler) http.Handler {`
_FUNC_SIG_RE = re.compile(r"^func\s+(\w+)\(([^)]*)\)\s*([\w.*\[\]]*)\s*\{", re.M)

_UNWRAPCALL = Path(__file__).resolve().parent.parent / "tools" / "unwrapcall.go"


def _param_types(params: str) -> str:
    """Normalise a parameter list to just its types: ``next http.Handler`` and
    ``http.Handler`` both become ``http.Handler``. Returns "" for anything with a
    shape we would rather not reason about."""
    out = []
    for part in (p.strip() for p in params.split(",") if p.strip()):
        fields = part.split()
        if len(fields) == 1:
            out.append(fields[0])       # a bare type, as in a func TYPE decl
        elif len(fields) == 2:
            out.append(fields[1])       # `name Type`
        else:
            return ""                   # variadic groups, multi-name params: bail
    return ", ".join(out)


def _fix_middleware_called_not_passed(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """``cannot use Logging(logger) (value of interface type http.Handler) as
    Middleware value in argument to Chain`` — the model declared the middleware
    correctly and then INVOKED it where it should have passed it::

        type Middleware func(http.Handler) http.Handler
        func Logging(next http.Handler) http.Handler { ... }   // already a Middleware

        Chain(mux, Logging(logger), Recover(logger))   // calls them
        Chain(mux, Logging, Recover)                   // should hand them over

    This is the same family as the register-the-method-value rule, and it is the
    mirror of the existing middleware-arity gate: that one repairs a DEFINITION
    written in the wrong shape, while here the definition is right and the CALL
    SITE is wrong. The two do not overlap.

    Provable: the repair fires only when the function's own signature is EXACTLY
    the underlying signature of the wanted named func type, in which case the
    function value is assignable to it by construction. Bails when the wanted type
    is not a func type declared by the project, when the signatures differ, or on
    any parameter list too exotic to normalise."""
    hits = list(_CALLED_ARG_RE.finditer(error_output))
    if not hits or not _UNWRAPCALL.exists():
        return {}

    # The project's named func types, as (params, result).
    func_types: dict[str, tuple[str, str]] = {}
    for p, c in written.items():
        if p.endswith(".go"):
            for name, params, result in _FUNC_TYPE_DECL_RE.findall(c):
                func_types[name] = (_param_types(params), result.strip())
    # The project's top-level functions, likewise.
    func_sigs: dict[str, tuple[str, str]] = {}
    for p, c in written.items():
        if p.endswith(".go"):
            for name, params, result in _FUNC_SIG_RE.findall(c):
                func_sigs[name] = (_param_types(params), result.strip())

    changed: dict[str, str] = {}
    for m in hits:
        path_hint, line, col, fn, _have, want, callee = (
            m.group(1), int(m.group(2)), int(m.group(3)),
            m.group(4), m.group(5), m.group(6), m.group(7),
        )
        wanted = func_types.get(want)
        actual = func_sigs.get(fn)
        if not wanted or not actual or not wanted[0] or wanted != actual:
            continue  # not a func type, unknown function, or signatures differ
        target = next(
            (p for p in written if os.path.basename(p) == os.path.basename(path_hint)),
            None,
        )
        if target is None:
            continue
        try:
            proc = subprocess.run(
                ["go", "run", str(_UNWRAPCALL), str(line), str(col), fn],
                input=changed.get(target, written[target]),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if proc.returncode != 0 or not proc.stdout.strip():
            continue
        changed[target] = proc.stdout
        _log(f"  passed {fn} to {callee} by value instead of calling it "
             f"(it is already a {want}) in {target}")
    return changed


# `service.go:102:18: multiple-value s.store.ListProjects(ctx) (value of type
# ([]models.Project, error)) in single-value context`
_MULTIVALUE_RE = re.compile(
    r"([\w./-]+\.go):(\d+):(\d+): multiple-value .+? in single-value context"
)

_HOISTCALL = Path(__file__).resolve().parent.parent / "tools" / "hoistcall.go"


def _fix_multivalue_in_single_context(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """``multiple-value s.store.ListProjects(ctx) (value of type
    ([]models.Project, error)) in single-value context`` — the store returns
    ``(items, error)`` and the model used the call as an argument, dropping the
    error on the floor. Go has no way to express that, so it does not compile::

        return paginate(s.store.ListProjects(ctx), limit, offset), nil

    The repair is what a Go programmer writes without thinking: hoist the call,
    handle the error, use the value::

        items, err := s.store.ListProjects(ctx)
        if err != nil {
                return nil, err
        }
        return paginate(items, limit, offset), nil

    This class sat un-gated for months, and for a real reason: unlike every other
    gate it must INTRODUCE statements rather than rewrite one. What makes it
    tractable is that the enclosing function's signature decides everything — the
    error goes to the last result, each earlier result takes its zero value — so
    ``tools/hoistcall.go`` reads it off the AST rather than guessing. It refuses
    whenever the signature does not settle the question: a function that does not
    end in ``error`` has nowhere to put it, and a named result type whose zero
    value cannot be inferred is not worth a guess."""
    hits = list(_MULTIVALUE_RE.finditer(error_output))
    if not hits or not _HOISTCALL.exists():
        return {}
    changed: dict[str, str] = {}
    for m in hits:
        path_hint, line, col = m.group(1), m.group(2), m.group(3)
        target = next(
            (p for p in written if os.path.basename(p) == os.path.basename(path_hint)),
            None,
        )
        if target is None:
            continue
        try:
            proc = subprocess.run(
                ["go", "run", str(_HOISTCALL), line, col],
                input=changed.get(target, written[target]),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if proc.returncode != 0 or not proc.stdout.strip():
            continue
        changed[target] = proc.stdout
        _log(f"  hoisted the two-value call at {target}:{line} into its own "
             f"statement and propagated the error")
    return changed


def _fix_self_qualified_package(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """``undefined: store`` in a file that IS ``package store``.

    The model wrote ``store.ErrNotFound`` inside the store package itself. Within
    a package you never qualify your own symbols — there is nothing named ``store``
    in scope, so the compiler reports the QUALIFIER as undefined rather than the
    symbol. It happens most in a test file, where the model is thinking of how the
    symbol looks from the outside.

    Safe by construction: inside package X, ``X.Sym`` is wrong under all
    circumstances (a package cannot import itself, and Go has no way to name it),
    so dropping the qualifier is the only thing it could have meant. The gate does
    it only for symbols the package actually declares, and refuses outright if the
    file imports anything whose own name is X — the one way X could legitimately be
    in scope. Line-preserving."""
    changed: dict[str, str] = {}
    undefined = {m.group(2) for m in _UNDEF_BARE_RE.finditer(error_output)}
    if not undefined:
        return {}
    for path, code in written.items():
        if not path.endswith(".go"):
            continue
        pkg = pkg_name_of(code)
        if not pkg or pkg not in undefined:
            continue
        # Everything this package declares, across all its files.
        own: set[str] = set()
        for p, c in written.items():
            if p.endswith(".go") and _dir_of(p) == _dir_of(path):
                own |= top_level_decls(c) | method_decls(c)
        if not own:
            continue
        # If some import is genuinely named `pkg`, the qualifier may be real.
        if any(
            imp.rsplit("/", 1)[-1] == pkg
            for imp in nonstdlib_imports(code) + _stdlib_imports(code)
        ):
            continue
        new = re.sub(
            rf"(?<![\w.]){re.escape(pkg)}\.(\w+)",
            lambda m: m.group(1) if m.group(1) in own else m.group(0),
            code,
        )
        if new != code:
            changed[path] = new
            _log(f"  {path} is package {pkg} — dropped the self-qualifier "
                 f"({pkg}.X is never valid inside {pkg})")
    return changed


# `invalid operation: operator ! not defined on tt.getWant.Error() (value of type
# string)`
_BANG_ON_NONBOOL_RE = re.compile(
    r"([\w./-]+\.go):(\d+):\d+: invalid operation: operator ! not defined on "
    r"(.+?) \(value of type \w[\w.\[\]*]*\)"
)


def _fix_negated_comparison(
    written: dict[str, str], error_output: str
) -> dict[str, str]:
    """``if !tt.getWant.Error() == "not found"`` — Go parses that as
    ``(!x) == y``, and ``!`` is not defined on a string, so it does not compile.

    The compiler is telling us the operand is NOT a bool, which means the
    expression could never have been valid as written — so there is no working
    program we might be changing the meaning of. And both readings of what the
    model meant converge on the same thing: ``!(x == y)`` and "x is not y" are
    both ``x != y``. That is what makes this repair unambiguous rather than a
    guess.

    Rewrites ``!<expr> == <rhs>`` to ``<expr> != <rhs>`` on the line the compiler
    named, using the exact operand text it printed. Line-preserving."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    for m in _BANG_ON_NONBOOL_RE.finditer(error_output):
        path, lineno, expr = resolve(m.group(1)), int(m.group(2)), m.group(3)
        if not path:
            continue
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        line = lines[lineno - 1]
        new = re.sub(
            rf"!{re.escape(expr)}\s*==\s*", f"{expr} != ", line, count=1
        )
        if new == line:
            continue
        lines[lineno - 1] = new
        changed[path] = "\n".join(lines) + ("\n" if code.endswith("\n") else "")
        _log(f"  {path}:{lineno}: `!x == y` cannot compile on a non-bool — "
             f"rewrote it as `x != y`")
    return changed


# `tt.listWant.Equal undefined (type []models.Task has no field or method Equal)`
_SLICE_EQUAL_RE = re.compile(
    r"([\w./-]+\.go):(\d+):\d+: ([\w.]+)\.Equal undefined "
    r"\(type (\[\][\w.]+) has no field or method Equal\)"
)


def _fix_slice_equal(written: dict[str, str], error_output: str) -> dict[str, str]:
    """``tt.listWant.Equal(got)`` — a slice has no ``Equal`` method, and never
    will. The model reached for one because most languages have it.

    The compiler prints the receiver's type, so we KNOW it is a slice, and Go has
    exactly one standard way to compare two of them: ``reflect.DeepEqual``. There
    is no second reading to choose between, which is what separates this from a
    guess. Shifts lines (it adds the import), so it lives in phase two."""
    changed: dict[str, str] = {}

    def resolve(path: str) -> str | None:
        path = path.lstrip("./")
        if path in written:
            return path
        cand = [p for p in written if p.endswith(path)]
        return cand[0] if len(cand) == 1 else None

    for m in _SLICE_EQUAL_RE.finditer(error_output):
        path, lineno, recv = resolve(m.group(1)), int(m.group(2)), m.group(3)
        if not path:
            continue
        code = changed.get(path, written[path])
        lines = code.splitlines()
        if lineno > len(lines):
            continue
        line = lines[lineno - 1]
        new = re.sub(
            rf"{re.escape(recv)}\.Equal\((.+?)\)",
            rf"reflect.DeepEqual({recv}, \1)",
            line,
            count=1,
        )
        if new == line:
            continue
        lines[lineno - 1] = new
        changed[path] = _ensure_import(
            "\n".join(lines) + ("\n" if code.endswith("\n") else ""), "reflect"
        )
        _log(f"  {path}:{lineno}: a slice has no Equal method — compared it with "
             f"reflect.DeepEqual")
    return changed


def _stdlib_imports(code: str) -> list[str]:
    """Import paths with no domain in the first segment — the standard library."""
    paths: list[str] = []
    for block in _IMPORT_BLOCK_RE.findall(code):
        paths.extend(_QUOTED_RE.findall(block))
    paths.extend(_IMPORT_SINGLE_RE.findall(code))
    return [p for p in paths if "." not in p.split("/")[0]]


def _run_deterministic_gates(
    written: dict[str, str], output: str, module: str | None
) -> dict[str, str]:
    """Run every deterministic, compiler-pinpointed repair on the current error
    output and return the merged {path: new_content} for changed files. Pure (no
    I/O) — the caller writes the result and re-runs the compiler.

    The gates run in TWO PHASES, and the split is not cosmetic — it is a
    correctness requirement that took a corrupted file to notice.

    Almost every gate is indexed by a line number the compiler just gave us. A
    gate that INSERTS a line — an import, a method on an interface, a hoisted
    statement — silently invalidates every one of those numbers for the rest of
    the pass. That is not hypothetical: in taskapipro, ``_requalify_undefined``
    added two imports to service_test.go, everything below shifted down by two,
    and ``_fix_assignment_arity`` then applied its repair to what used to be line
    40 and is now something else entirely — turning

        tk1 := models.Task{ID: "1", ...}     into     tk1, _ := models.Task{...}

    which is not valid Go under any circumstances, and which no later gate could
    undo. The fix loop then burned every remaining round on a file the gates
    themselves had broken.

    So: phase one runs only the repairs that rewrite a line IN PLACE, and they are
    safe together because none of them changes how many lines a file has. If any
    of them fires we return immediately, and the caller re-compiles — so the next
    pass gets fresh line numbers.

    Phase two runs the line-SHIFTING repairs, one at a time, returning after the
    first that fires. Each of them makes the compiler's numbers stale, so no
    second gate may run behind it.
    """
    # --- Phase 1: in-place repairs. Every one of these rewrites a line and leaves
    # the line COUNT alone, so the compiler's numbers stay valid for all of them
    # and they are safe to run together. Which gates qualify was settled by
    # measurement, not by reading — see tests/test_gate_line_safety.py, which
    # caught three of them misfiled here on its first run.
    inplace: dict[str, str] = {}
    inplace.update(_fix_assignment_arity(written, output))
    inplace.update(_fix_unused_var({**written, **inplace}, output))
    inplace.update(_fix_uncalled_method_value({**written, **inplace}, output))
    inplace.update(_fix_undefined_assignment({**written, **inplace}, output))
    inplace.update(_fix_if_composite_literal({**written, **inplace}, output))
    inplace.update(_fix_swapped_error_assignment({**written, **inplace}, output))
    inplace.update(_fix_fatal_guard({**written, **inplace}, output))
    inplace.update(_fix_handle_vs_handlefunc({**written, **inplace}, output))
    inplace.update(_fix_atomic_inc({**written, **inplace}, output))
    inplace.update(_fix_struct_literal_key({**written, **inplace}, output))
    inplace.update(_fix_mux_return_type({**written, **inplace}, output))
    inplace.update(_fix_handlerfunc_wrap({**written, **inplace}, output))
    inplace.update(_fix_pointer_to_interface({**written, **inplace}, output))
    inplace.update(_fix_self_qualified_package({**written, **inplace}, output))
    inplace.update(_fix_negated_comparison({**written, **inplace}, output))
    if inplace:
        return inplace

    # --- Phase 2: repairs that MOVE lines — an import added, a struct field
    # inserted or removed, a method appended to an interface, a statement hoisted,
    # a file reformatted by go/format. Each makes the compiler's line numbers
    # stale, so exactly one runs per pass and nothing runs behind it. The caller
    # re-compiles and the next pass starts from fresh numbers.
    for gate in (
        lambda w: _requalify_undefined(w, output, module),
        lambda w: _requalify_stdlib(w, output),
        lambda w: _fix_module_prefix(w, output, module),
        lambda w: _fix_phantom_local_import(w, output, module),
        lambda w: _fix_string_int_conversion(w, output),
        lambda w: _fix_errors_wrap(w, output),
        lambda w: _fix_unknown_struct_fields(w, output),
        lambda w: _fix_duplicate_struct_fields(w, output),
        lambda w: _fix_middleware_arity(w, output),
        lambda w: _fix_interface_missing_method(w, output),
        lambda w: _fix_shadowed_tester(w, output),
        # Phase 2 because it SPLICES statements in (a rebuild plus a replay of the
        # request's mutations), which moves every line below it.
        lambda w: _fix_drained_request(w, output),
        # Phase 2 because it DELETES statements, which moves every line below them.
        lambda w: _fix_dead_error_assertion(w, output),
        lambda w: _fix_missing_constructor_alias(w, output),
        lambda w: _fix_argument_type_adapter(w, output),
        lambda w: _fix_middleware_called_not_passed(w, output),
        lambda w: _fix_multivalue_in_single_context(w, output),
        lambda w: _fix_slice_equal(w, output),
    ):
        shifted = gate(written)
        if shifted:
            return shifted
    return {}


_ASSERTION_RE = re.compile(r"\bt\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\b")

# `Event struct {Type, TaskID string}` named in a file's PURPOSE — the type is
# part of the file's contract with the rest of the project. A qualified
# mention (http.Handler interface) is another package's type, not ours.
_REQUIRED_TYPE_RE = re.compile(r"(?<![.\w])([A-Z]\w*)\s+(?i:struct|interface)\b")


def _required_decls(purpose: str) -> set[str]:
    """Type names the purpose explicitly promises this file will define. A
    candidate missing one compiles alone but breaks every package that was
    told (via the same spec) to reference it — the models.Event omission that
    no later fix round recovers, because each fix keeps resampling from the
    same blind prior."""
    required = set(_REQUIRED_TYPE_RE.findall(purpose or ""))
    # `package main` needs its entrypoint: a main.go without func main fails
    # with a package-level error that carries NO file:line to route on
    if re.search(r"\bfunc main\b|\bmain\(\)", purpose or ""):
        required.add("main")
    return required


def _foreign_owned_decls(
    files: Sequence[FileSpec], target_path: str, own_purpose: str
) -> set[str]:
    """Domain types OWNED by other packages' purposes (models.Task promised by
    models.go). A candidate for THIS file redeclaring one creates the
    dup-domain-type collapse — two structurally different store.Task /
    models.Task that nothing can convert between. Treated like sibling decls:
    stripped from candidates, and the bare references left behind are then
    requalified to the owner (models.Task) by the existing gates."""
    target_dir = _dir_of(target_path)
    owned: set[str] = set()
    for f in files:
        if _dir_of(f.path) != target_dir:
            owned |= _required_decls(f.purpose)
    return owned - _required_decls(own_purpose)


def has_assertions(code: str) -> bool:
    """True if a Go test file contains at least one failing assertion. A test
    with no ``t.Error``/``t.Fatal``/… can pass trivially without testing
    anything, so we reject such candidates during best-of-N for *_test.go files."""
    return bool(_ASSERTION_RE.search(code))


_LOCK_CALL_RE = re.compile(r"\b([A-Za-z_]\w*(?:\.\w+)*)\.(?:RLock|Lock)\(\)")
_DEFER_UNLOCK_CALL_RE = re.compile(
    r"\bdefer\s+([A-Za-z_]\w*(?:\.\w+)*)\.(?:RUnlock|Unlock)\(\)"
)
_FUNC_HEADER_RE = re.compile(r"\bfunc\b[^{;]*\{", re.S)


def _func_bodies(code: str):
    """Yield (name, body) for each top-level func/method, matching braces.

    Regex, like the rest of the check chain — the toolchain is not invoked to
    decide a candidate is dirty. Nested braces inside the body are balanced by
    counting, so a struct literal or closure does not truncate the body.
    """
    for fm in _FUNC_HEADER_RE.finditer(code):
        header = code[fm.start():fm.end()]
        m = (re.search(r"\)\s*([A-Za-z_]\w*)\s*\(", header)
             or re.search(r"\bfunc\s+([A-Za-z_]\w*)\s*\(", header))
        name = m.group(1) if m else "func"
        depth, i, n = 1, fm.end(), len(code)
        while i < n and depth:
            if code[i] == "{":
                depth += 1
            elif code[i] == "}":
                depth -= 1
            i += 1
        yield name, code[fm.end():i - 1]


def mutex_self_deadlock(code: str) -> set[str]:
    """Methods that acquire a mutex AGAIN after deferring its unlock — a deadlock.

    shortener 2026-07-17 shipped Resolve() = RLock(); defer RUnlock(); ...; Lock().
    A read lock cannot be upgraded to a write lock on the same sync.RWMutex, so it
    blocks forever — a test TIMEOUT, never a compile error. mutex_rule's prose is
    entirely cross-method ("call ANOTHER method"), and an A/B (mutex-intra) proved
    a sentence teaching the intra-method shape does NOT stop the model writing it:
    the prior "RLock the read half, Lock the write half" wins over the prompt.

    So it belongs in a check, by the same rule as self_dropped_decls: decidable
    FROM THE FILE ALONE, no spec, no purpose, no call graph. If a method DEFERS
    the unlock of a mutex M — holding M until the function returns — and then
    acquires M again anywhere after that defer, the second acquire is nested
    inside the first on a non-reentrant lock and deadlocks UNCONDITIONALLY.

    Deliberately narrow, because a gate that rejects correct code is worse than
    none: it flags ONLY deferred-then-reacquired, which cannot be anything but a
    deadlock. It does not touch the cross-method case (a call graph, and
    mutex_rule's job) and does not flag Lock/Unlock/Lock sequential code. Validated
    against every mutex-bearing artifact in the suite: 3/3 on the deadlocked files,
    0 false positives on 14 correct ones.
    """
    bad: set[str] = set()
    for name, body in _func_bodies(code):
        for dm in _DEFER_UNLOCK_CALL_RE.finditer(body):
            mutex = dm.group(1)
            if any(lk.group(1) == mutex for lk in _LOCK_CALL_RE.finditer(body[dm.end():])):
                bad.add(name)
                break
    return bad


def self_dropped_decls(candidate: str, previous: str, sibling_decls: set[str] | None) -> set[str]:
    """Package-scope names ``previous`` declared, ``candidate`` no longer declares,
    and ``candidate`` still REFERENCES — with no sibling to provide them.

    A rewrite that does this cannot compile, and it says so in the compiler's own
    words: `undefined: failStore`. Across every A/B log on disk this exact shape
    appears 33 times over 13 runs, and three of those runs burned their whole fix
    budget on it, oscillating — round 4 drops `fakeEnqueuer`, round 5 puts it back
    and drops `failStore`. The fix loop rewrites the WHOLE test file each round,
    and the package-scope fixtures at the top are the part it forgets.

    The machinery to catch this looked present and was not. `_is_clean`'s
    `required_decls` is the right idea and misses on two counts at once: it is
    switched off for test files (`if is_go and not is_test`), and its regex wants
    an exported name (`([A-Z]\\w*)\\s+(?i:struct|interface)`) while these fixtures
    are `failStore` and `fakeEnqueuer`. The fix path's `must_keep` protects only
    symbols OTHER packages reference, and nothing outside a test file references
    its own fake. Three guards, all real, none of them looking here.

    This one needs no spec, no purpose text and no list of names: the candidate
    is self-inconsistent. It uses what it does not define. That is decidable from
    the two versions alone, which is why it belongs here rather than in a prompt.
    """
    if not previous:
        return set()
    dropped = (top_level_decls(previous) | method_decls(previous)) - (
        top_level_decls(candidate) | method_decls(candidate)
    ) - (sibling_decls or set())
    return {n for n in dropped if re.search(rf"\b{re.escape(n)}\b", candidate)}


# Named for what they strip out of a movedecls payload — NOT _IMPORT_BLOCK_RE,
# which already exists at module scope and is what nonstdlib_imports reads with.
# Redefining it here silently rebound that name for the whole module and made the
# import scanner return a duplicate; two tests caught it immediately, which is the
# only reason this comment is a note and not another retraction.
_MOVED_PKG_CLAUSE_RE = re.compile(r"\A\s*package\s+\w+\s*$", re.MULTILINE)
_MOVED_IMPORTS_RE = re.compile(r"^import\s*\((?:[^)]*)\)\s*$|^import\s+\S.*$", re.MULTILINE)


def _moved_payload(previous: str, names: set[str]) -> str:
    """The bodies `movedecls` lifts out of ``previous`` for ``names`` — package
    clause and imports stripped, ready to append."""
    pkg = re.search(r"^package\s+(\w+)", previous, re.MULTILINE)
    if not pkg or not _MOVEDECLS.exists():
        return ""
    try:
        proc = subprocess.run(
            ["go", "run", str(_MOVEDECLS), pkg.group(1), ",".join(sorted(names))],
            input=previous, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0 or not proc.stdout.strip():
        return ""
    try:
        moved = json.loads(proc.stdout).get("moved", "")
    except json.JSONDecodeError:
        return ""
    return _MOVED_IMPORTS_RE.sub("", _MOVED_PKG_CLAUSE_RE.sub("", moved, count=1)).strip()


def restore_dropped_decls(candidate: str, previous: str, names: set[str]) -> str:
    """Splice back the package-scope declarations ``candidate`` dropped but still
    uses, lifting them — with their methods — out of ``previous``.

    REJECTING these was not enough, and the run said so rather than my reasoning:

        fixing internal/service/service_test.go
          best-of-N fix: no clean candidate; using the first of 2
        ! vet: internal/service/service_test.go:169:24: undefined: failStore

    Both draws dropped `failStore` — temp 0.1 AND the temp 0.6 retry. The model
    drops this fixture wherever you sample from, so resampling cannot clear it.
    That is this project's own law arriving at my own work: a nudge is not a gate.

    `movedecls` already lifts a declaration and everything bound to it out of a
    file, so given the previous version it returns `failStore` with its methods —
    exactly the cluster the rewrite lost. Append the bodies, drop the payload's
    package clause and imports, let goimports settle the rest on write.

    CLOSE THE NAME SET FIRST, splice ONCE. I wrote this the obvious way — splice,
    then recurse on the output — and it appended `failStore` twice while still
    leaving `errBoom` undefined. Restoring a type restores its methods, and those
    methods call things the same rewrite dropped WITHOUT still using them, so the
    first pass never flagged them: the repair introduces the undefined it was
    called to remove. The real artifact happened to keep `errBoom` and the repair
    looked total. A distilled test of the same shape caught it in seconds, which
    is the only reason "safe by construction" is not in this docstring twice.

    What IS true by construction: every name added is declared by ``previous``,
    a version that compiled with them, and is referenced by the code being
    repaired. The caller re-checks the result and drops the repair wholesale if it
    is still self-inconsistent, so a closure that cannot close changes nothing.

    KNOWN LIMIT, stated because the alternative is finding it in a red run:
    `movedecls` moves TYPE and FUNC declarations only (`if t.Tok != token.TYPE`),
    so a dropped `var` or `const` is out of reach. If the closure needs one — a
    restored method calling a dropped `var errBoom` — the payload comes back
    without it, the result is still self-inconsistent, and the caller drops the
    repair: a no-op, not a corruption. The real recorded failure kept `errBoom`
    and lost only `failStore`, which is why the repair takes that artifact from
    `go vet` rc=1 to a full green build+vet+test. Teaching movedecls to move vars
    would widen this, and it is NOT a free change: `_fill_empty_planned_files`
    shares that tool, and moving vars it currently leaves alone would alter a gate
    that works. Measure that separately or leave it.
    """
    if not names or not previous.strip():
        return candidate
    # Top-level names ONLY. Including method_decls here put `List` in the closure,
    # movedecls does not take a method name, the payload came back empty, and the
    # function returned the candidate UNREPAIRED — a silent no-op that the unit
    # test caught and a live run would have hidden behind "the model dropped it".
    have = top_level_decls(previous)
    wanted = set(names) & have
    for _ in range(len(have) + 1):  # bounded by previous's own declarations
        payload = _moved_payload(previous, wanted)
        if not payload:
            return candidate
        needed = {n for n in have - wanted if re.search(rf"\b{re.escape(n)}\b", payload)}
        if not needed:
            return candidate.rstrip() + "\n\n" + payload + "\n"
        wanted |= needed
    return candidate


def why_dirty(
    code: str,
    is_go: bool,
    toolchain: GoToolchain,
    sibling_decls: set[str] | None = None,
    require_assertions: bool = False,
    required_decls: set[str] | None = None,
    module: str | None = None,
    previous: str | None = None,
) -> str:
    """The name of the first check ``code`` fails, for the log. Empty if clean.

    `no clean candidate` never said WHICH rule rejected, and that gap cost real
    reasoning: a rejection landed in the same round as an `undefined: failStore`,
    the two looked consistent, and I was one inference from crediting the rule I
    had just written. Consistent is not proof. A candidate can be rejected for a
    foreign import while the round goes red for something else entirely — the log
    has to say which, or the next reader takes a correlation for a cause.
    """
    if not is_go:
        return ""
    if not toolchain.syntax_ok(code):
        return "does not parse"
    if foreign := nonstdlib_imports(code, module):
        return f"foreign import: {', '.join(foreign)}"
    if sibling_decls and (clash := (top_level_decls(code) | method_decls(code)) & sibling_decls):
        return f"redeclares a sibling's {', '.join(sorted(clash))}"
    if required_decls and (missing := required_decls - top_level_decls(code)):
        return f"missing promised {', '.join(sorted(missing))}"
    if previous and (gone := self_dropped_decls(code, previous, sibling_decls)):
        return f"drops {', '.join(sorted(gone))} — still used, no sibling declares it"
    if deadlocked := mutex_self_deadlock(code):
        return (f"{', '.join(sorted(deadlocked))} re-locks a mutex it already holds"
                " (deferred unlock) — deadlocks")
    if require_assertions and not has_assertions(code):
        return "asserts nothing"
    return ""


def _is_clean(
    code: str,
    is_go: bool,
    toolchain: GoToolchain,
    sibling_decls: set[str] | None = None,
    require_assertions: bool = False,
    required_decls: set[str] | None = None,
    module: str | None = None,
    previous: str | None = None,
) -> bool:
    """A clean Go candidate parses, imports nothing foreign (the standard library
    and the project's OWN packages are both fine), does not redeclare a sibling's
    package-level symbol, declares every type its purpose promises, does not drop
    a declaration it still uses, and — for test files — actually asserts something.

    ``module`` must be threaded through for a multi-package project. Without it,
    the project's own imports count as foreign and NO candidate is ever clean."""
    if not is_go:
        return True
    if not toolchain.syntax_ok(code) or nonstdlib_imports(code, module):
        return False
    if sibling_decls and ((top_level_decls(code) | method_decls(code)) & sibling_decls):
        return False
    if required_decls and not required_decls <= top_level_decls(code):
        return False
    if previous and self_dropped_decls(code, previous, sibling_decls):
        return False
    if mutex_self_deadlock(code):
        return False
    if require_assertions and not has_assertions(code):
        return False
    return True


def _resample_temperature(attempt: int) -> float | None:
    """The temperature for best-of-N's ``attempt``-th draw. None = the default.

    BEST-OF-N WAS A NO-OP FOR ITS ENTIRE LIFE, and the logs said so in a number I
    had never looked at. Across every A/B log on disk:

        kept candidate 1 of 2 : 2905
        kept candidate 2 of 2 :    0     <- the resample NEVER rescued a draw
        no clean candidate    :  320     <- ...it failed identically, 320 times

    The cause is one line above this function: every attempt called
    ``coder.generate(prompt)`` with the SAME prompt, and this server is
    deterministic — same (prompt, temperature) in, byte-identical text out
    (measured: three 1200-token completions at temp=0.1, identical; seeds
    1/999/123456 at temp=2.0, identical). So candidate 2 was candidate 1. Drawing
    it again could only reproduce the same defect, which is exactly what those
    320 rows are: a dirty sample, redrawn, dirty in precisely the same way.
    Zero rescues out of 320 is not bad luck. It is a mechanism that never fired
    while the project's own notes marked it "best-of-N ✓".

    Temperature is the one handle that does move the output: temp=0.1 and
    temp=0.6 on an identical prompt return genuinely different files, while each
    stays deterministic at its own value. So attempt 0 keeps the near-greedy
    default — the common path is unchanged, and a clean first draw still returns
    without a second call — and each retry steps the temperature, buying a real
    alternative sample WITHOUT giving up reproducibility.
    """
    if attempt == 0:
        return None
    base = float(os.environ.get("GUILDLM_BUILDER_TEMP", "0.1"))
    step = float(os.environ.get("GUILDLM_BUILDER_RESAMPLE_STEP", "0.5"))
    return base + step * attempt


def _sample_clean(
    coder: Coder,
    prompt: str,
    is_go: bool,
    candidates: int,
    toolchain: GoToolchain,
    what: str,
    sibling_decls: set[str] | None = None,
    require_assertions: bool = False,
    required_decls: set[str] | None = None,
    module: str | None = None,
    previous: str | None = None,
) -> str:
    """Draw up to ``candidates`` samples; keep the first clean one (parses,
    stdlib-only, no cross-file redeclaration, and — for test files — actually
    asserts something). Used for BOTH generation and fixes, so a stubborn small
    model that re-adds a forbidden import (gorilla/mux), crams a sibling's types
    into this file, or writes a trivially-passing test gets resampled instead of
    poisoning the build. Falls back to the last sample so progress never stalls.
    """
    last = ""
    first = ""
    for attempt in range(max(1, candidates)):
        last = extract_code(coder.generate(prompt, _resample_temperature(attempt)))
        if attempt == 0:
            first = last
        if is_go and sibling_decls:
            # Deterministically drop any declaration a sibling already owns
            # (the redeclared-sentinel/type collapse) — the dead import it
            # leaves behind is pruned by goimports on write.
            stripped = strip_redeclarations(last, sibling_decls)
            if stripped != last:
                _log(f"    stripped redeclared symbols from {what} candidate")
                last = stripped
        if _is_clean(last, is_go, toolchain, sibling_decls, require_assertions,
                     required_decls, module, previous):
            _log(f"    best-of-N {what}: kept candidate {attempt + 1} of {candidates}")
            return last
        # Name the rule that rejected it — ANY of them, not just the one I happen
        # to be interested in. A log that only reports my own check's rejections
        # is how a correlation gets read as a cause.
        if reason := why_dirty(last, is_go, toolchain, sibling_decls,
                               require_assertions, required_decls, module, previous):
            _log(f"    rejected {what} candidate {attempt + 1}: {reason}")
    if candidates > 1:
        # Fall back to the FIRST draw, not the last. They used to be the same
        # object — an identical prompt against a deterministic server — so "last"
        # was harmless. Now that a retry steps the temperature, "last" is the
        # HOTTEST sample, and this branch is exactly the case where every draw was
        # dirty: 320 times on the logs. Shipping the hottest reject in place of the
        # near-greedy one would be a regression introduced by the repair that made
        # best-of-N work at all. Attempt 0 is the conservative draw; when nothing
        # is clean, it is what the loop used before and what it should use now.
        _log(f"    best-of-N {what}: no clean candidate; using the first of {candidates}")
        first = first or last
    else:
        first = first or last
    # The repair behind the rejection. Measured, not assumed: both draws dropped
    # the same fixture, so no amount of resampling brings it back — but the
    # previous version still has it, verbatim, and the candidate still calls it.
    if previous and (gone := self_dropped_decls(first, previous, sibling_decls)):
        restored = restore_dropped_decls(first, previous, gone)
        if restored != first and not self_dropped_decls(restored, previous, sibling_decls):
            _log(f"    restored {', '.join(sorted(gone))} into {what} candidate — "
                 f"the rewrite dropped what it still calls")
            return restored
    return first


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
    must_keep: set[str] | None = None,
    module: str | None = None,
) -> str:
    """Fix-loop best-of-N with a GROUND-TRUTH gate: sample up to ``candidates``
    repairs, write each in place, and keep the first that makes the *whole
    project* build, vet and test cleanly. Falls back to the best parse-clean
    candidate (then the last sample) so a round always makes progress.

    ``must_keep`` are exported symbols OTHER packages reference (``pkg.Sym``).
    A repair that deletes one fixes this file by breaking every importer — the
    models.Event collapse — so such candidates are rejected outright, and if
    every sample deletes them the CURRENT file is kept unchanged.

    This is verification-driven *selection* — the very ``go`` feedback the loop
    already trusts, applied at candidate-pick time rather than only after. A
    stubborn small model that keeps re-emitting the same wrong test expectation
    (it can't see why `want` is wrong) gets out-voted by the one sampled
    candidate that actually goes green, instead of the loop keeping whichever
    parses. Most decisive when a single file is the culprit — exactly when the
    parse-only gate is blindest.
    """
    is_go = path.endswith(".go")

    def keeps_referenced(code: str) -> bool:
        if not must_keep or not is_go:
            return True
        return must_keep <= (top_level_decls(code) | method_decls(code))

    original = written.get(path, "")
    best_clean: str | None = None
    last = original
    for attempt in range(max(1, candidates)):
        cand = extract_code(coder.generate(prompt))
        if is_go and sibling_decls:
            cand = strip_redeclarations(cand, sibling_decls)
        last = cand
        if not keeps_referenced(cand):
            continue
        if not _is_clean(cand, is_go, toolchain, sibling_decls, is_test,
                         module=module):
            continue
        if best_clean is None:
            best_clean = cand
        written[path] = _write_file(out, path, cand)
        ok, _ = toolchain.check(out)
        if ok:
            # Log EVERY success, not just a second-candidate one. Suppressing the
            # common case is exactly what hid best-of-N being dead for months: its
            # success log also fired only when `attempt` was truthy, so a
            # mechanism that never selected anything and a mechanism that always
            # picked candidate 1 produced identical, silent logs.
            _log(f"    verified fix: candidate {attempt + 1} turns the project green")
            return cand
    chosen = best_clean if best_clean is not None else last
    if not keeps_referenced(chosen) and keeps_referenced(original):
        # only guard against DELETION — when the symbols never existed, the
        # best remaining candidate may still fix something else
        _log(f"    rejected every fix of {path} — each deletes exported "
             f"symbols other packages reference; keeping the current file")
        chosen = original
    written[path] = _write_file(out, path, chosen)
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
        retriever.top_k(
            f"{task.spec.path} {task.spec.purpose}", shots,
            prefer_tests=task.spec.path.endswith("_test.go"),
        )
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
            sibling_decls |= top_level_decls(content) | method_decls(content)
    # domain types other packages' purposes own (models.Task): stripping a
    # local redeclaration leaves bare references the requalify gate resolves
    # to the owner — instead of a second, unconvertible store.Task
    sibling_decls |= _foreign_owned_decls(spec.files, task.spec.path, task.spec.purpose)
    is_test = task.spec.path.endswith("_test.go")
    required = (
        _required_decls(task.spec.purpose) - sibling_decls
        if is_go and not is_test
        else None
    )
    code = _sample_clean(
        coder, prompt, is_go, candidates, toolchain, "gen", sibling_decls,
        is_test, required, module=spec.go_module or None
    )
    _trace({"stage": "generate", "path": task.spec.path,
            "prompt": prompt, "response": code})
    return code


# How many progress-gated rounds may follow the flat budget (see _fix_loop).
_EXTENSION_ROUNDS = 3

# Run-specific noise in toolchain/test output that must not make two otherwise
# identical error surfaces look different: heap addresses, goroutine ids, test
# wall times, and the pointer-suffixed frame offsets in panic traces.
_SIG_NOISE_RE = re.compile(
    r"0x[0-9a-f]+|goroutine \d+|\d+\.\d+s|\+0x[0-9a-f]+"
)


def _error_signature(output: str) -> str:
    """A normalized fingerprint of a check's error output, stable across reruns
    of the SAME failure but different across genuinely new error strata."""
    return _SIG_NOISE_RE.sub("?", output)


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
    retriever: "Retriever | None" = None,
    shots: int = 0,
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
    # Local imports the deterministic requalify pass established, per file.
    # A model regeneration of that file tends to DROP them again (the run-#6
    # oscillation); re-pinning after every model fix makes the deterministic
    # repair stick permanently. An import that becomes unused is pruned by
    # goimports on write, so re-adding is always safe.
    pinned: dict[str, set[str]] = {}
    # dir -> runtime-failure rounds seen, for root-cause target widening
    runtime_rounds: dict[str, int] = {}
    # Progress-gated extension: a layered project peels one error stratum per
    # round (build -> vet -> test-compile -> panics -> assertions), so the last
    # stratum routinely surfaces exactly when the flat budget runs out. Extra
    # rounds are granted ONLY while each check exposes an error surface never
    # seen before (normalized: addresses/goroutines/timings stripped) — real
    # convergence continues, oscillation stops immediately.
    seen_surfaces: set[str] = set()
    rnd = 0
    while rnd < max_fix_rounds + _EXTENSION_ROUNDS:
        rnd += 1
        sig = _error_signature(output)
        if rnd > max_fix_rounds and sig in seen_surfaces:
            _log("error surface repeats — stopping extension rounds")
            break
        seen_surfaces.add(sig)
        label = (f"fix round {rnd}/{max_fix_rounds}" if rnd <= max_fix_rounds
                 else f"extension round {rnd} (new error surface)")
        _log(f"compile/test FAILED, {label}")
        # Print the error the loop is actually reacting to. Without this the log
        # states the verdict and withholds the reason, so every diagnosis starts
        # by re-deriving what the toolchain already said — the same error-surface
        # blindness that hid failures from the gates, turned on the operator. Five
        # lines is enough to name the stratum (parse vs type vs assertion) and
        # cheap enough to keep on by default.
        for _line in [ln for ln in output.splitlines() if ln.strip()][:5]:
            _log(f"    ! {_line.strip()}")
        # Deterministic pre-pass, run to a FIXPOINT: each gate sweep can expose
        # the next mechanical stratum (a vet repair lets the test stage run at
        # all, whose panics feed the fatal-guard gate), so sweep until the
        # gates go quiet. Whatever still fails afterwards is the model's BY
        # CONSTRUCTION — which also kills the old oscillation where a
        # gate-repaired file was handed straight back to the model in the same
        # round (the model re-broke it, the gates re-fixed it, forever).
        #
        # The budget is generous because a pass now does LESS: since the gates
        # were split into phases, a pass applies either the in-place repairs or a
        # SINGLE line-shifting one, so a project needing several imports, a struct
        # field and a hoisted call needs several passes to work through them.
        # taskapipro takes seven. The loop still stops the moment the gates go
        # quiet — the cap only guards a pathological rewrite cycle.
        for _ in range(30):
            requal = _run_deterministic_gates(written, output, module)
            if not requal:
                break
            for path, content in requal.items():
                _log(f"  deterministic fix in {path}")
                written[path] = _write_file(out, path, content)
                if module:
                    pinned.setdefault(path, set()).update(
                        re.findall(rf'"({re.escape(module)}/[^"]+)"', content)
                    )
            ok, output = check(out)
            if ok:
                _log(f"converged to green after fix round {rnd} (deterministic)")
                return True
        targets = _offending_files(output, list(written)) or list(written)
        targets = _widen_runtime_targets(targets, written, runtime_rounds, output)
        targets = _widen_missing_symbol_targets(targets, written, output)
        targets = _widen_promised_symbol_targets(
            targets, written, output, [t.spec for t in tasks]
        )
        # go.mod is fully determined by the module path (stdlib-only projects) —
        # never hand it to the model (one bad sample poisons EVERY later round:
        # parse errors mask the real diagnostics). Restore it deterministically.
        if module and "go.mod" in targets:
            fresh = _gomod_content(module)
            if written.get("go.mod") != fresh:
                _log("  restored go.mod deterministically")
                written["go.mod"] = _write_file(out, "go.mod", fresh)
            targets = [t for t in targets if t != "go.mod"]
        for path in targets:
            task = _task_for(tasks, path)
            if task is None:
                continue
            _log(f"  fixing {path}")
            fix_shots = (
                retriever.top_k(
                    f"{task.spec.path} {task.spec.purpose}", shots,
                    prefer_tests=path.endswith("_test.go"),
                )
                if retriever and shots
                else None
            )
            fix_prompt = _fix_prompt(task, written[path], output, written,
                                     shots=fix_shots)
            fix_dir = _dir_of(path)
            sibling_decls: set[str] = set()
            for other, content in written.items():
                if other != path and _dir_of(other) == fix_dir:
                    sibling_decls |= top_level_decls(content) | method_decls(content)
            # other packages' purpose-owned domain types: a fix redeclaring
            # one recreates the dup-domain-type collapse — strip/reject it
            sibling_decls |= _foreign_owned_decls(
                [t.spec for t in tasks], path, task.spec.purpose)
            # Exported symbols of THIS file that other packages reference as
            # pkg.Sym — a "fix" that deletes one breaks every importer (the
            # models.Event collapse), so it must never be accepted.
            must_keep: set[str] = set()
            if path.endswith(".go") and not path.endswith("_test.go"):
                own_pkg = pkg_name_of(written[path])
                if own_pkg and own_pkg != "main":
                    used: set[str] = set()
                    for other, content in written.items():
                        if _dir_of(other) != fix_dir:
                            used.update(re.findall(
                                rf"\b{re.escape(own_pkg)}\.(\w+)", content))
                    must_keep = used & top_level_decls(written[path])
                # types the PURPOSE promises must exist even if the initial
                # generation omitted them — otherwise no fix ever adds them
                must_keep |= _required_decls(task.spec.purpose) - sibling_decls
            # The verified path writes each candidate and checks the WHOLE
            # project, keeping the one that turns it green. That is only
            # ACHIEVABLE when this file is the last thing standing: with other
            # files still broken, no fix to this one can green the project, so the
            # check cannot succeed and the second sample is drawn for nothing.
            # It shows: `verified fix: candidate N turns the project green` has
            # never once been logged across 163 real runs. So spend the extra
            # generation only when it can pay — when this is the only file being
            # fixed this round.
            if candidates > 1 and len(targets) == 1:
                code = _sample_verified_fix(
                    coder, fix_prompt, path, out, written, candidates, toolchain,
                    sibling_decls, path.endswith("_test.go"), must_keep,
                    module=module,
                )
            else:
                # `previous` is what makes the self-consistency check possible: a
                # candidate that drops a package-scope name it still uses is
                # rejected and RESAMPLED. That rejection was worthless until
                # today — an identical prompt against a deterministic server
                # returned an identical candidate, so a redraw reproduced the
                # same defect (0 rescues in 320 redraws). Now a retry steps the
                # temperature and comes back genuinely different, so rejecting is
                # worth doing.
                code = _sample_clean(
                    coder, fix_prompt, path.endswith(".go"), candidates, toolchain,
                    "fix", sibling_decls, path.endswith("_test.go"),
                    must_keep or None, module=module, previous=written[path],
                )
                old_decls = top_level_decls(written[path]) | method_decls(written[path])
                new_decls = top_level_decls(code) | method_decls(code)
                if must_keep and not (must_keep <= new_decls) and (
                    must_keep <= old_decls
                ):
                    _log(f"  rejected fix of {path} — it deletes exported "
                         f"symbols other packages reference")
                else:
                    written[path] = _write_file(out, path, code)
            repinned = written[path]
            for imp in pinned.get(path, ()):
                repinned = _ensure_import(repinned, imp)
            if repinned != written[path]:
                _log(f"  re-pinned local imports in {path}")
                written[path] = _write_file(out, path, repinned)
            _trace({"stage": "fix", "path": path,
                    "prompt": fix_prompt, "response": written[path]})
        ok, output = check(out)
        if ok:
            _log(f"converged to green after fix round {rnd}")
            return True
    # Final deterministic pass: the gates run BEFORE each model fix, so a
    # mechanical bug the model introduces in the LAST round (a re-appeared
    # string(int), a blank-fixable arity, a truncated import) has no later
    # pre-pass to catch it. Run the gates to a FIXPOINT, not one shot — fixing
    # one mechanical layer routinely uncovers the next (a vet repair lets the
    # TEST stage run at all, whose panics feed yet another gate), and each
    # iteration costs only a check. Gates are idempotent, and every iteration
    # must change a file to continue, so the loop always terminates; the cap
    # only guards against a pathological rewrite cycle. Generous for the same
    # reason as the pre-pass: one line-shifting gate per pass means more passes.
    for _ in range(30):
        final = _run_deterministic_gates(written, output, module)
        if not final:
            break
        for path, content in final.items():
            _log(f"  final deterministic fix in {path}")
            written[path] = _write_file(out, path, content)
        ok, output = check(out)
        if ok:
            _log("converged to green on the final deterministic pass")
            return True
    _log(f"exhausted {rnd} fix rounds ({max_fix_rounds} budgeted), still failing")
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
        # A green build is not the same as the project that was asked for. When
        # the model implements a sibling's job in its own file, the sibling ends
        # up with nothing left to declare and ships as a bare `package store` —
        # and Go, which does not care which file in a package holds what, greens
        # anyway. Four of the suite's multi-package artifacts carried a dead file
        # like this and nothing ever said so.
        _fill_empty_planned_files(spec, written, out, toolchain)
        for path in empty_go_files(written):
            _log(f"  WARNING: {path} shipped EMPTY — a sibling did its job; the "
                 f"project does not match its own plan")
        if reviewer is not None and review_rounds > 0:
            _log("review pass (catch bugs that survive a green build)")
            _review_pass(spec, tasks, written, out, toolchain, reviewer, review_rounds)
        # the harvester keeps a trace's pairs only when this event closes it —
        # final file contents are included because a pair's response may have
        # been superseded by later fixes; the green FILE is the verified truth
        _trace({"event": "green", "spec": spec.name, "files": written})
        return True, written

    # --- Generation pass ---------------------------------------------------- #
    for task in tasks:
        _log(f"generate {task.spec.path} ({task.index + 1}/{len(tasks)})")
        if task.spec.path == "go.mod" and spec.go_module:
            code = _gomod_content(spec.go_module)  # deterministic, never sampled
        else:
            code = _generate_file(
                coder, spec, task, written, candidates, toolchain, retriever, shots
            )
        written[task.spec.path] = _write_file(out, task.spec.path, code)

    # --- Fix loop ----------------------------------------------------------- #
    # Scale the round budget with project size: a multi-package project spends
    # its early rounds on the mechanical compile layers (qualification, arity,
    # imports), and the semantic test layer only becomes VISIBLE once
    # everything builds — with a flat budget it surfaces exactly when no
    # rounds are left. One round per ~4 files, floored at the caller's value.
    rounds = max(max_fix_rounds, -(-len(tasks) // 4))
    if rounds > max_fix_rounds:
        _log(f"fix-round budget scaled to {rounds} for {len(tasks)} files")
    if _fix_loop(tasks, written, out, toolchain, coder, rounds, candidates,
                 module=spec.go_module, retriever=retriever, shots=shots):
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
                sib |= top_level_decls(content) | method_decls(content)
        code = _sample_clean(
            coder, _maintain_file_prompt(request, path, current, is_new),
            path.endswith(".go"), candidates, toolchain, "edit", sib, path.endswith("_test.go"),
        )
        current[path] = _write_file(out, path, code)

    def _tasks() -> list[FileTask]:
        return [
            FileTask(index=i, spec=FileSpec(path=p, purpose=f"maintained for change: {request}"))
            for i, p in enumerate(current)
        ]

    impl_targets = [p for p in targets if not p.endswith("_test.go")]
    test_targets = [p for p in targets if p.endswith("_test.go")]

    # The project's own module path, so a candidate importing a SIBLING package is
    # not mistaken for one reaching out to gorilla/mux — the bug that silently
    # killed candidate selection in every multi-package project.
    _mm = re.search(r"^module\s+(\S+)", current.get("go.mod", ""), re.M)
    module = _mm.group(1) if _mm else None

    for path in impl_targets:
        _edit(path)
    if impl_targets:
        _log("staged maintain: converging the implementation (build+vet) before tests")
        _fix_loop(_tasks(), current, out, toolchain, coder, max_fix_rounds, candidates,
                  check=toolchain.build_vet, module=module)
    for path in test_targets:
        _edit(path)

    # 4. full verify (build+vet+test) + repair to green
    tasks = _tasks()
    if _fix_loop(tasks, current, out, toolchain, coder, max_fix_rounds, candidates,
                 module=module):
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
            sibling_decls |= top_level_decls(c) | method_decls(c)
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
    current[test_filename] = _write_file(out, test_filename, code)
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
            candidate = _write_file(out, path, candidate)
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


def _write_file(out: Path, rel_path: str, content: str) -> str:
    """Write (gofmt'd) and RETURN the exact content that landed on disk.

    Callers must store the return value in ``written`` — not the pre-gofmt
    input. gofmt reflows files, so keeping the raw content desynchronizes
    ``written`` line numbers from the compiler's file:line diagnostics, and
    every line-indexed deterministic gate (arity, string(int), undefined-
    assignment) then silently misses its target line."""
    if rel_path.endswith(".go"):
        content = gofmt_code(content)
    dest = out / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return content


# --------------------------------------------------------------------------- #
# Spec lint — catch a self-defeating spec before it costs a run
# --------------------------------------------------------------------------- #

# Every rule below is a failure that actually happened, cost a full generation,
# and was only diagnosed by reading the artifact afterwards. All of them were
# visible in the YAML the whole time.

_FRESH_PER_CASE_RE = re.compile(
    r"fresh\s+[\w.()+]+\s+per\s+case"          # "Fresh NewMemStore per case"
    r"|per\s+case[,.]?\s+fresh"
    r"|each\s+case\s+\w+\s+(a|its\s+own)\s+fresh"  # "Each case builds a FRESH router"
    r"|fresh\s+\w+[\w.()+]*\s+for\s+each\s+case",
    re.I,
)

# A spec that forbids the model's natural idiom does not win the argument. The
# 7B writes a `Store` INTERFACE in every single generation; tasks-api told
# store.go to make Store a concrete struct and "do NOT model it as an
# interface", and across five rolls the model wrote the interface anyway — three
# times alongside a StoreImpl (so nothing named NewStore existed) and twice
# alongside a Store STRUCT (`Store redeclared in this block`). The collision was
# manufactured by the ask. The fix that worked was to stop fighting: let the
# interface have the name, and give the implementation a different one.
_FIGHTS_PRIOR_RE = re.compile(
    r"(do\s+NOT|don't|never)\s+model\s+it\s+as\s+an?\s+interface"
    r"|not\s+an\s+interface\b"
    r"|\(NOT\s+an\s+interface\)",
    re.I,
)
_PRECONDITION_RE = re.compile(
    r"dup(licate)?\b[^.]{0,40}(409|ErrExists)"
    r"|get\s+(present|existing)"
    r"|existing\s+\w+\s*->\s*200"
    r"|delete\s+present",
    re.I,
)
# A constructor the PROJECT must declare. The lookbehind is what makes it mean
# that: `httptest.NewRecorder()` and `slog.NewTextHandler()` are the standard
# library's, not ours, and matching them turns this rule into noise.
_CTOR_CALL_RE = re.compile(r"(?<![.\w])(New[A-Z]\w*)\s*\(")


def lint_spec(spec: Spec) -> list[str]:
    """Static contradictions in a spec, found without running anything.

    A generation costs minutes of GPU; several of this project's most expensive
    debugging sessions ended at a spec that could not be satisfied by ANY
    implementation. Those are cheap to catch by reading the YAML, and this reads
    it.
    """
    problems: list[str] = []
    tests = [f for f in spec.files if f.path.endswith("_test.go")]
    impls = [
        f for f in spec.files
        if f.path.endswith(".go") and not f.path.endswith("_test.go")
    ]

    for f in tests:
        purpose = f.purpose or ""

        # 1. The seeding trap. "Fresh store per case" plus "duplicate -> 409" is
        #    unsatisfiable: on a store nobody wrote to there is nothing to
        #    duplicate and nothing to fetch. Seen in SEVEN specs.
        if _FRESH_PER_CASE_RE.search(purpose) and _PRECONDITION_RE.search(purpose):
            if not re.search(r"seed|create.{0,30}first|POST.{0,20}(first|ONCE)", purpose, re.I):
                problems.append(
                    f"{f.path}: asks for a FRESH instance per case AND a case with a "
                    f"precondition (a duplicate, or an existing record). A fresh "
                    f"instance is empty, so no implementation can pass both — say "
                    f"the case must CREATE its precondition first."
                )

        # 2. A test that calls a constructor nobody is asked to write. The
        #    compiler says `undefined: NewStore` and the fix loop cannot invent
        #    it; tasks-api burned five rounds on exactly this.
        for ctor in set(_CTOR_CALL_RE.findall(purpose)):
            if not any(ctor in (i.purpose or "") for i in impls):
                problems.append(
                    f"{f.path}: calls {ctor}(), but no implementation file's "
                    f"purpose promises to declare it — the build will fail with "
                    f"`undefined: {ctor}`."
                )

    # 3. One name asked to be two things -> `X redeclared in this block`.
    for f in impls:
        purpose = f.purpose or ""
        for m in re.finditer(r"\b([A-Z]\w*)\s+interface\b", purpose):
            name = m.group(1)
            if re.search(rf"\b{re.escape(name)}\s+struct\b", purpose):
                problems.append(
                    f"{f.path}: names {name} as BOTH an interface and a struct — "
                    f"that is `{name} redeclared in this block`. Name the "
                    f"implementation something else (e.g. Mem{name})."
                )

        # 4. A purpose that forbids the model's idiom. Empirically the spec loses
        #    this argument, and the loss is expensive: five rolls, five broken
        #    store.go. Name the two things differently instead of banning one.
        if _FIGHTS_PRIOR_RE.search(purpose):
            problems.append(
                f"{f.path}: forbids the model from using an interface. It will "
                f"write one anyway — every generation does — and the ban only "
                f"decides HOW it breaks (a StoreImpl nothing calls, or two "
                f"declarations of the same name). Let the interface keep the "
                f"name and give the implementation a different one."
            )

    return problems


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
        # A generation costs minutes of GPU, and several of the most expensive
        # debugging sessions on this project ended at a spec no implementation
        # could satisfy. Say so before spending the time, not after.
        for problem in lint_spec(spec_obj):
            _log(f"  spec-lint: {problem}")
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
