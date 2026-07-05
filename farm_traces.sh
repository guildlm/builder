#!/usr/bin/env bash
# Self-distillation data farm: run the Builder over every spec with tracing
# on, then harvest the green runs into on-policy SFT pairs. Each run's trace
# lands in traces/<spec>-<n>.jsonl; harvest_traces.py keeps only pairs whose
# run ended verified green (build+vet+test). $0, local, serial (one MLX server).
#
# Usage: ./farm_traces.sh [rounds-per-spec (default 1)]
set -uo pipefail
cd "$(dirname "$0")"

ROUNDS="${1:-1}"
MODEL="${GUILDLM_FARM_MODEL:-mlx-community/Qwen2.5-Coder-7B-Instruct-4bit}"
BASE_URL="${GUILDLM_FARM_BASE_URL:-http://localhost:8080/v1}"
SPECS="${GUILDLM_FARM_SPECS:-usersapi taskflow taskapi taskapipro workapi jsonapi kvservice numkit workerpool tasks-api}"

mkdir -p traces farm

for round in $(seq 1 "$ROUNDS"); do
  for spec in $SPECS; do
    [ -f "specs/$spec.yaml" ] || { echo "skip $spec (no spec)"; continue; }
    stamp="$(date +%m%d%H%M%S)"
    out="farm/$spec-$stamp"
    trace="traces/$spec-$stamp.jsonl"
    echo "=== farm: $spec (round $round) -> $out"
    GUILDLM_BUILDER_TRACE="$trace" .venv/bin/guildlm-build main \
      --spec "specs/$spec.yaml" --out "$out" \
      --model "$MODEL" --base-url "$BASE_URL" \
      --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
      && echo "=== $spec GREEN" || echo "=== $spec failed (trace kept for diagnosis, no harvest)"
  done
done

.venv/bin/python harvest_traces.py traces/*.jsonl -o distill_onpolicy.jsonl
