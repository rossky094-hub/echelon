#!/usr/bin/env bash
# Step6 fusion 失败后从 fusion 续跑至 report
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs/v14b
LOG="$ROOT/logs/v14b/e2e_continue.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
set -a; source "$ROOT/.env"; set +a
log "========== 续跑 fusion → report =========="
for step in fusion mutation layout report; do
  log ">>> make ${step}"
  make "$step" >> "$LOG" 2>&1 && log ">>> make ${step} OK" || { log ">>> make ${step} FAILED"; exit 1; }
done
log "========== 主流程完成 =========="
