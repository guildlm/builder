#!/usr/bin/env python3
"""Insert an inert block at the END of named file entries in a spec, structurally.

    python _mkvariant_ratelimit.py <src.yaml> <out.yaml> <block.txt> <path> [<path>...]

WHY STRUCTURAL AND NOT A TEXT ANCHOR. Every ratelimit entry's purpose ends with the same
sentence, "Standard library only.", so no closing phrase is unique. The jsoncodec run already
lost an attempt to a text anchor: its purpose is a FOLDED scalar, YAML wrapped the phrase I
keyed on across two lines, grep never matched it, and a throwaway uniqueness check reported a
confident "1" from a failed lookup. Entry boundaries are unique by construction and indifferent
to how YAML wrapped the prose.

THE LAST-ENTRY BRANCH IS LOAD-BEARING, not defensive: ratelimit_test.go is both the final entry
and one of the targets, so "run to the next `  - path:`" is not enough on its own.
"""
import sys

def main(argv):
    src, out, block_path, targets = argv[0], argv[1], argv[2], set(argv[3:])
    lines = open(src).read().splitlines(keepends=True)
    block = open(block_path).read().splitlines(keepends=True)
    starts = [i for i, l in enumerate(lines) if l.startswith("  - path:")]
    assert starts, "no file entries found"
    paths = [lines[i].split("path:", 1)[1].strip() for i in starts]
    missing = targets - set(paths)
    assert not missing, f"targets not present in the spec: {sorted(missing)}"

    def entry_end(k):
        if k + 1 < len(starts):
            return starts[k + 1]
        for j in range(starts[k] + 1, len(lines)):
            s = lines[j]
            if s.strip() and not s.startswith("    ") and not s.startswith("  - "):
                return j
        return len(lines)

    res, done, tail = lines[:starts[0]], [], []
    for k, s in enumerate(starts):
        e = entry_end(k)
        res.extend(lines[s:e])
        if paths[k] in targets:
            res.extend(block)
            done.append(paths[k])
        if k + 1 == len(starts):
            tail = lines[e:]
    res.extend(tail)
    open(out, "w").writelines(res)
    assert set(done) == targets, f"inserted into {done}, wanted {sorted(targets)}"
    print(f"  inserted {len(block)} lines at the end of each of: {', '.join(done)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
