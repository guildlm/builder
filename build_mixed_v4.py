#!/usr/bin/env python3
"""Assemble the mixed-v4 7B SFT dataset for the distillation wheel.

train = mixed-v2 base SFT (2553 rows) + on-policy distill (58 rows, seq-4096
budget) oversampled x4, deterministically shuffled (seed 42).
valid = unchanged mixed-v2 valid split (so eval loss stays comparable to v2/v3).

Both inputs already share the {"messages":[...]} chat format.
"""
import json
import os
import random
import sys

ROOT = os.path.expanduser("~/Desktop/Personal/Dev/guildlm")
MIXED_TRAIN = os.path.join(ROOT, ".mlx-data-godev-mixed/train.jsonl")
MIXED_VALID = os.path.join(ROOT, ".mlx-data-godev-mixed/valid.jsonl")
DISTILL = os.path.join(ROOT, "builder/distill_train_4k.jsonl")
OUT_DIR = os.path.join(ROOT, ".mlx-data-godev-mixed-v4-7b")
OVERSAMPLE = 4


def load(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main():
    base = load(MIXED_TRAIN)
    distill = load(DISTILL)
    if not base or not distill:
        print("ERROR: empty input", file=sys.stderr)
        sys.exit(1)

    train = list(base) + distill * OVERSAMPLE
    rng = random.Random(42)
    rng.shuffle(train)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "train.jsonl"), "w") as f:
        for r in train:
            f.write(json.dumps(r) + "\n")

    # valid unchanged from mixed base
    valid = load(MIXED_VALID)
    with open(os.path.join(OUT_DIR, "valid.jsonl"), "w") as f:
        for r in valid:
            f.write(json.dumps(r) + "\n")

    print(f"mixed base:   {len(base)}")
    print(f"distill:      {len(distill)} x{OVERSAMPLE} = {len(distill)*OVERSAMPLE}")
    print(f"train total:  {len(train)}  ({100*len(distill)*OVERSAMPLE/len(train):.1f}% distill)")
    print(f"valid:        {len(valid)}")
    print(f"-> {OUT_DIR}")


if __name__ == "__main__":
    main()
