# Sourced by the experiment runners. Not executable on its own.
#
#     source ./_harness_lock.sh
#     harness_lock_init "$0" "$SPEC" "$EXAMPLES"     # once, before any draw
#     harness_check || return $?                     # before EVERY draw
#
# THE HARNESS MUST NOT MOVE UNDER A MULTI-HOUR RUN. Every draw is a fresh `guildlm-build` process
# that re-reads src/builder.py, so an edit landing mid-run puts some draws on one harness and the
# rest on another — and the whole design of a paired A/B is that control and arm share a commit.
# On 31 July this nearly happened: a one-line logging change was queued, would have been applied
# between pairs, and was caught only because I stopped to check.
#
# HASHED, NOT `git rev-parse HEAD`. Measured the same day: appending a line to src/builder.py
# leaves HEAD unchanged and changes the file. A HEAD guard would have missed exactly the edit it
# was written to catch. `git status --porcelain` catches THAT case but answers "is the tree dirty",
# not "is it what I started with" — a file edited and reverted to a different commit's content
# reads clean and is wrong.
#
# EVERY INPUT A DRAW READS, not just the code. A draw also reads the SPEC and the EXAMPLES file,
# and the spec is the MOST-EDITED file in this campaign — 191 edits on record, against a handful
# for the runners. Guarding builder.py while leaving the spec free would watch the quiet door and
# leave the busy one open. src/__init__.py is 31 bytes and imports nothing; left out deliberately.
#
# ⚠️ SHARED ON PURPOSE. _parity_ab.sh and _parity_xproc.sh both need this, and a copy in each is
# the drift _selftest_freeze_guard.sh was written to prevent — that test SOURCES this file and
# drives these functions directly, and separately asserts that each runner uses them rather than
# inlining its own copy. A guard can be perfect and unused.

harness_lock_init () {   # <runner> [extra files...]
  # this file is part of the harness too — a guard whose own definition can change mid-run is
  # not a guard. It is sourced once at start, so an edit would not reach the running process; it
  # is locked so the RECORD of what a run used stays honest.
  HARNESS_FILES=(src/builder.py "${BASH_SOURCE[0]}" "$@")
  WANT_HARNESS=$(harness_hash)
  echo "=== harness locked at ${WANT_HARNESS:0:16} (${#HARNESS_FILES[@]} files: builder + $*) ==="
}

harness_hash () { shasum "${HARNESS_FILES[@]}" | awk '{print $1}' | tr -d '\n'; }

harness_check () {
  local now; now=$(harness_hash)
  [[ "$now" == "$WANT_HARNESS" ]] || {
    echo "REFUSING: the harness changed mid-run (${WANT_HARNESS:0:16} -> ${now:0:16})."
    echo "  Draws already taken used the OLD harness; continuing would split this experiment"
    echo "  across two versions of the code. Restart the run, or revert src/builder.py."
    return 6; }
  return 0
}
