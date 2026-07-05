#!/usr/bin/env python3
"""Turn harvested on-policy pairs into TRAINING rows that fit the SFT budget.

Builder inference prompts run ~18-36k chars (project context + retrieval
shots); the mlx LoRA recipe trains at seq 2048 (~7800 chars). Feeding the raw
prompts would truncate mid-context, so this converter PRUNES each instruction
while keeping the parts that carry the signal we want baked into the weights:

  * DROP the retrieval-examples block entirely — the whole point of
    distillation is that the model INTERNALIZES the contracts, so the
    training input must not lean on them;
  * COMPRESS full sibling-file bodies to their exported API surface (the
    same summary the Builder already shows for other packages);
  * KEEP the target-file header, purpose, project file list, cross-package
    rules and the final write instruction.

Rows still over budget after pruning are dropped (logged), not truncated —
a clipped Go file teaches broken Go. Output is mlx-lm chat format
({"messages": [...]}), same SYSTEM prompt as the mixed go-dev recipe.

Usage:
    python distill_prep.py distill_onpolicy.jsonl -o distill_train.jsonl \
        [--max-chars 7800]
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from src.builder import exported_api

SYSTEM = ("You are GuildLM go-dev, an expert Go engineer. Write idiomatic, "
          "correct, complete Go. When code is requested, respond with Go code.")

# Section headers of the generation/fix prompts, in the order they can appear.
_RETRIEVAL_START = "Similar verified Go examples for reference"
_AFTER_RETRIEVAL = (
    "Already-written files in THIS package",
    "OTHER-PACKAGE APIs",
    "--- other files in THIS package",
    "--- OTHER-PACKAGE APIs",
    "--- current ",
    "Write the complete contents",
    "The Go toolchain reported errors",
)
_SIBLING_FILE_RE = re.compile(
    r"--- ([\w./-]+\.go) ---\n(.*?)(?=\n--- |\nOTHER-PACKAGE|\nWrite the |\Z)",
    re.DOTALL,
)


def _drop_retrieval(prompt: str) -> str:
    i = prompt.find(_RETRIEVAL_START)
    if i == -1:
        return prompt
    ends = [j for h in _AFTER_RETRIEVAL if (j := prompt.find(h, i)) != -1]
    if not ends:
        return prompt[:i]
    return prompt[:i] + prompt[min(ends):]


def _compress_siblings(prompt: str) -> str:
    def repl(m: re.Match) -> str:
        path, body = m.group(1), m.group(2)
        if path.endswith("_test.go") or len(body) < 600:
            return m.group(0)  # short files / tests stay whole
        return f"--- {path} (exported API) ---\n{exported_api(body)}\n"

    return _SIBLING_FILE_RE.sub(repl, prompt)


def prep(rows: list[dict], max_chars: int) -> tuple[list[dict], int]:
    out, dropped = [], 0
    for r in rows:
        instr = _compress_siblings(_drop_retrieval(r["instruction"]))
        total = len(SYSTEM) + len(instr) + len(r["response"])
        if total > max_chars:
            dropped += 1
            continue
        out.append({"messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": instr},
            {"role": "assistant", "content": r["response"]},
        ]})
    return out, dropped


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("inp", help="harvested pairs (distill_onpolicy.jsonl)")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--max-chars", type=int, default=7800)
    args = ap.parse_args(argv[1:])

    rows = [json.loads(l) for l in open(args.inp, encoding="utf-8") if l.strip()]
    out, dropped = prep(rows, args.max_chars)
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    kept_lens = sorted(
        sum(len(m["content"]) for m in r["messages"]) for r in out
    )
    mid = kept_lens[len(kept_lens) // 2] if kept_lens else 0
    print(f"kept {len(out)}/{len(rows)} rows (dropped {dropped} over "
          f"{args.max_chars} chars) -> {args.out}; median {mid} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
