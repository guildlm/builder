#!/usr/bin/env python3
"""Harvest Builder traces into on-policy SFT data for self-distillation.

The Builder (with GUILDLM_BUILDER_TRACE=<file> set) records every accepted
(prompt, response) pair plus a final ``green`` event carrying the verified
file contents. This script turns those traces into instruction/response rows:

  * only traces whose final event is ``green`` contribute (toolchain-verified
    end-to-end: build + vet + test);
  * for each generated file, the LAST prompt that targeted it is paired with
    the FINAL green content — later deterministic gates may have improved the
    file after the model's last answer, and the green file is the verified
    truth we want the model to produce in one shot;
  * go.mod is skipped (deterministic, never model-written).

This is the training half of the flywheel: data in the Builder's OWN
inference format, execution-verified, $0. Usage:

    python harvest_traces.py traces/*.jsonl -o distill.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _fence(code: str) -> str:
    return f"```go\n{code.rstrip()}\n```"


def harvest(trace_path: Path) -> list[dict]:
    entries: list[dict] = []
    try:
        with open(trace_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  ! skipping {trace_path}: {e}", file=sys.stderr)
        return []
    green = next((e for e in reversed(entries) if e.get("event") == "green"), None)
    if green is None:
        return []
    files: dict[str, str] = green.get("files", {})
    last_prompt: dict[str, str] = {}
    for e in entries:
        if e.get("stage") in ("generate", "fix") and e.get("path") in files:
            last_prompt[e["path"]] = e["prompt"]
    rows = []
    for path, prompt in last_prompt.items():
        if not path.endswith(".go"):
            continue  # go.mod etc. are deterministic, never model-written
        rows.append({
            "instruction": prompt,
            "response": _fence(files[path]),
            "meta": {"spec": green.get("spec"), "path": path,
                     "trace": trace_path.name},
        })
    return rows


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("traces", nargs="+", help="trace JSONL files (one per run)")
    ap.add_argument("-o", "--out", required=True, help="output SFT JSONL")
    args = ap.parse_args(argv[1:])

    seen: set[str] = set()
    rows: list[dict] = []
    green_runs = 0
    for p in args.traces:
        got = harvest(Path(p))
        if got:
            green_runs += 1
        for r in got:
            key = r["instruction"][:2000] + " " + r["response"][:2000]
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"harvested {len(rows)} verified pairs from {green_runs} green runs "
          f"({len(args.traces)} traces scanned) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
