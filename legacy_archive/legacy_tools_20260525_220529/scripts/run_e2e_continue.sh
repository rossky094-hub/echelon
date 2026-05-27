#!/usr/bin/env bash
# 从 Step5 续跑至 Step9（跳过已有 checkpoint 的步骤）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs/v14b

LOG="$ROOT/logs/v14b/e2e_continue.log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

log "========== V14-B 续跑 Step5-9 开始 =========="
log "LLM_PROVIDER=${LLM_PROVIDER:-?}"

STEPS=(scibert vgae limitation fusion mutation layout report)
for step in "${STEPS[@]}"; do
  log ">>> make ${step}"
  if make "$step" >> "$LOG" 2>&1; then
    log ">>> make ${step} OK"
  else
    log ">>> make ${step} FAILED"
    exit 1
  fi
done

log "========== V14-B Step5-9 全部完成 =========="
log "报告: reports/v14b_pilot/V14B_Pilot_算法验证报告.md"
