#!/usr/bin/env bash
# V14-B 端到端 Pilot：Step1 enrich → Step2-9，自动续跑 checkpoint
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs/v14b

LOG="$ROOT/logs/v14b/e2e_pilot.log"
CK_STEP1="$ROOT/reports/v14b_pilot/checkpoints/step1_enrich.done.json"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

# 加载 .env
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

log "========== V14-B E2E Pilot 开始 =========="
log "LLM_PROVIDER=${LLM_PROVIDER:-?} OPENALEX_EMAIL=${OPENALEX_EMAIL:-?} CONCURRENCY=${V14B_CONCURRENCY:-10}"

# ---------- Step 1: OpenAlex Enrich ----------
if [[ -f "$CK_STEP1" ]]; then
  log "Step1 checkpoint 已存在，跳过 enrich"
else
  if pgrep -f "echelon.v14b.step1_enrich" >/dev/null 2>&1; then
    log "检测到 Step1 正在运行，等待完成..."
    while pgrep -f "echelon.v14b.step1_enrich" >/dev/null 2>&1; do
      sleep 120
      n=$(sqlite3 "$ROOT/db/echelon_library.sqlite3" \
        "SELECT COUNT(*) FROM papers WHERE openalex_enriched=1;" 2>/dev/null || echo "?")
      log "  enrich 进度: 已成功 ${n}/13606"
    done
    log "Step1 进程已结束"
  else
    log "启动 Step1 enrich..."
    make enrich 2>&1 | tee -a "$LOG"
  fi
fi

log "链接 paper_references 内部 ID..."
python3 -c "
from echelon.v14b.config import DB_MAIN
from echelon.v14b.step1_enrich import link_paper_reference_internals
import sqlite3
conn = sqlite3.connect(str(DB_MAIN))
link_paper_reference_internals(conn)
conn.close()
"

# ---------- Step 2-9 ----------
STEPS=(mainpath keystone subgraph scibert vgae limitation fusion mutation layout report)
for step in "${STEPS[@]}"; do
  log ">>> make ${step}"
  if make "$step" >> "$LOG" 2>&1; then
    log ">>> make ${step} OK"
  else
    log ">>> make ${step} FAILED (exit $?)"
    exit 1
  fi
done

log "========== V14-B E2E Pilot 全部完成 =========="
log "报告: reports/v14b_pilot/V14B_Pilot_算法验证报告.md"
log "报告: reports/v14b_pilot/未来方向预测_交集报告.md"
