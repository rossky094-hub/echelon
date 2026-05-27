#!/usr/bin/env bash
# 从 Step5c 续跑至 Step9（5a/5b 已完成时使用）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs/v14b

LOG="$ROOT/logs/v14b/e2e_continue.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

log "========== 续跑 limitation → report =========="

STEPS=(limitation fusion mutation layout report)
for step in "${STEPS[@]}"; do
  log ">>> make ${step}"
  if make "$step" >> "$LOG" 2>&1; then
    log ">>> make ${step} OK"
  else
    log ">>> make ${step} FAILED"
    exit 1
  fi
done

log "========== 全部完成 =========="
