#!/usr/bin/env bash
# Restart mlx_lm.server and return only when it can actually INFER.
#
#     ./_server_restart.sh            # kill, relaunch, wait for a real completion
#     ./_server_restart.sh --check    # report state and readiness, kill nothing
#
# Written for the corrected parity design (1 pair x 3 PROCESSES), where process identity is the
# thing being varied: logs/PREREG-the-parity-effect-across-processes-not-across-draws.txt.
# _parity_ab.sh assumes ONE process for the whole run and pins it with _server_pid.sh; this is the
# piece that lets a run cross the boundary deliberately instead of by accident.
#
# ⚠️ READINESS IS A COMPLETION, NOT /v1/models. Measured 31 July: /v1/models answers in 0.157s and
# LISTS THE HF CACHE rather than the loaded model — it returned Qwen2.5-3B-Instruct while the 7B
# coder was serving. Polling it would start a draw against a server still loading weights, and that
# first draw would differ from the rest of its pair for reasons unrelated to the manipulation.
#
# ⚠️ AND IT REFUSES WHILE A DRAW IS RUNNING. Killing the server under a live build destroys 20-95
# minutes of GPU work; this repo has a standing rule against destructive commands run beside a live
# build for exactly that reason.
set -uo pipefail
cd "$(dirname "$0")"

MODEL="${MODEL:-mlx-community/Qwen2.5-Coder-7B-Instruct-4bit}"
PORT="${PORT:-8080}"
CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1

ready () {   # a real 1-token completion; the only self-validating readiness signal
  curl -s -m 20 "http://localhost:$PORT/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d '{"model":"x","messages":[{"role":"user","content":"hi"}],"max_tokens":1,"temperature":0}' \
    2>/dev/null | grep -q '"choices"'
}

old=$(./_server_pid.sh 2>/dev/null) || old=""
echo "  current server pid   ${old:-<none>}"

if pgrep -f "\.venv/bin/guildlm-build" >/dev/null; then
  echo "  ** A DRAW IS IN FLIGHT — refusing to restart. **"
  echo "     Killing the server now would destroy a build that has been running for minutes."
  pgrep -lf "\.venv/bin/guildlm-build" | head -3 | sed 's/^/       /'
  [[ $CHECK -eq 1 ]] || exit 7
fi

if [[ $CHECK -eq 1 ]]; then
  # ⚠️ DO NOT PROBE A BUSY SERVER. Measured 31 July against a healthy pid 7598 that was serving a
  # draw: the completion probe TIMED OUT at 20s and reported NOT READY. mlx_lm.server serialises,
  # so the probe queued behind the draw's generation. The probe answers "can it serve ME right
  # now", NOT "is it loaded" — and reading it as the latter would declare a working server dead.
  # It also puts a request on a server that is running an experiment, which is its own reason.
  if pgrep -f "\.venv/bin/guildlm-build" >/dev/null; then
    echo "  readiness            NOT PROBED — a draw is using the server; the probe would queue"
    echo "                       behind it and time out, which means nothing about server health."
    exit 0
  fi
  t0=$(python3 -c 'import time;print(time.time())')
  if ready; then verdict="READY (a real completion returned)"; else verdict="NOT READY (no completion)"; fi
  t1=$(python3 -c 'import time;print(time.time())')
  printf '  readiness            %s in %.1fs\n' "$verdict" "$(python3 -c "print($t1-$t0)")"
  echo "  /v1/models says      $(curl -s -m 3 "http://localhost:$PORT/v1/models" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(", ".join(x["id"] for x in d.get("data",[]))[:120])' 2>/dev/null || echo '<no answer>')"
  echo "     ^ this is the HF CACHE listing, not the loaded model. Never use it as a readiness probe."
  exit 0
fi

[[ -n "$old" ]] && { echo "  killing $old"; kill "$old"; }
for _ in $(seq 1 40); do
  pgrep -f "mlx_lm.server" >/dev/null || break
  perl -e 'select undef,undef,undef,0.5'
done
pgrep -f "mlx_lm.server" >/dev/null && { echo "  ** old server did not exit **"; exit 8; }

log="logs/mlx-server-restart-$(date +%H%M%S).out"
nohup .venv/bin/python -m mlx_lm.server --model "$MODEL" --port "$PORT" > "$log" 2>&1 &
echo "  relaunched, log $log"

start=$(python3 -c 'import time;print(time.time())')
for i in $(seq 1 120); do
  if ready; then
    new=$(./_server_pid.sh 2>/dev/null)
    printf '  READY after %.0fs · new pid %s (was %s)\n' \
      "$(python3 -c "import time;print(time.time()-$start)")" "$new" "${old:-<none>}"
    [[ "$new" == "$old" ]] && { echo "  ** pid unchanged — this is NOT a new process **"; exit 9; }
    exit 0
  fi
  perl -e 'select undef,undef,undef,1'
done
echo "  ** never became ready **"; exit 10
