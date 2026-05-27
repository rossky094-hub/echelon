#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export VECLIB_MAXIMUM_THREADS="${VECLIB_MAXIMUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
export V14B_EMBEDDING_BATCH_SIZE="${V14B_EMBEDDING_BATCH_SIZE:-16}"
export V14B_CITATION_CLASSIFIER="${V14B_CITATION_CLASSIFIER:-heuristic}"
export V14B_LIMITATION_USE_LLM="${V14B_LIMITATION_USE_LLM:-false}"
export V14B_AUDIT_FAIL_ON="${V14B_AUDIT_FAIL_ON:-none}"

LOG="logs/v14b/step5b6_algorithm_audit_chain.log"
mkdir -p "$(dirname "$LOG")"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

{
  log "start patched Step5b"
  python3 -m echelon.v14b.step5b_vgae \
    --db db/echelon_library.sqlite3 \
    --db-v14 db/v14_pilot.sqlite3 \
    --no-resume

  log "start patched Step5c"
  python3 -m echelon.v14b.step5c_limitation \
    --db db/echelon_library.sqlite3 \
    --db-v14 db/v14_pilot.sqlite3 \
    --no-resume

  log "start patched Step6"
  python3 -m echelon.v14b.step6_fusion \
    --db db/echelon_library.sqlite3 \
    --db-v14 db/v14_pilot.sqlite3 \
    --no-resume

  log "patched Step5b-Step6 chain done"
} >> "$LOG" 2>&1
