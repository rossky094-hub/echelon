#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export VECLIB_MAXIMUM_THREADS="${VECLIB_MAXIMUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
export V14B_EMBEDDING_BATCH_SIZE="${V14B_EMBEDDING_BATCH_SIZE:-16}"
export V14B_AUDIT_FAIL_ON="${V14B_AUDIT_FAIL_ON:-none}"

LOG="logs/v14b/post_step6_product_chain.log"
mkdir -p "$(dirname "$LOG")"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

{
  log "start Step7-Step10 after Step1-Step6 audit"
  make mutation layout report visual-graph
  log "Step7-Step10 done"
} >> "$LOG" 2>&1
