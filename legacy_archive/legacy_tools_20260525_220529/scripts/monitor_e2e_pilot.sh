#!/usr/bin/env bash
# 守护：1) 主流程 Step5c→9  2) 未 enrich 论文补齐
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs/v14b reports/v14b_pilot/checkpoints

LOG="$ROOT/logs/v14b/monitor.log"
REPORT1="$ROOT/reports/v14b_pilot/V14B_Pilot_算法验证报告.md"
REPORT2="$ROOT/reports/v14b_pilot/未来方向预测_交集报告.md"
INTERVAL="${MONITOR_INTERVAL_SEC:-7200}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

reports_done() {
  [[ -f "$REPORT1" && -f "$REPORT2" ]] && \
    [[ $(wc -c < "$REPORT1" | tr -d ' ') -gt 500 ]] && \
    [[ $(wc -c < "$REPORT2" | tr -d ' ') -gt 200 ]]
}

e2e_running() {
  pgrep -f "run_e2e_from_limitation|run_e2e_continue|echelon.v14b.step[5-9]" >/dev/null 2>&1
}

enrich_running() {
  pgrep -f "echelon.v14b.step1_enrich" >/dev/null 2>&1
}

pending_enrich() {
  sqlite3 "$ROOT/db/echelon_library.sqlite3" \
    "SELECT COUNT(*) FROM papers WHERE openalex_enriched IS NULL OR openalex_enriched=0;" 2>/dev/null || echo 0
}

start_e2e() {
  if [[ -f "$ROOT/reports/v14b_pilot/checkpoints/step5c_limitation.done.json" ]]; then
    log "启动主流程(从 fusion): run_e2e_from_limitation 仅 fusion+ 或需新脚本"
    # step5c 完成后用 limitation 脚本的后半段 — 同脚本会 skip limitation
    nohup bash "$ROOT/scripts/run_e2e_from_limitation.sh" >> "$ROOT/logs/v14b/e2e_continue_nohup.log" 2>&1 &
  elif [[ -f "$ROOT/reports/v14b_pilot/checkpoints/step5b_vgae.done.json" ]]; then
    log "启动主流程: run_e2e_from_limitation (limitation→report)"
    nohup bash "$ROOT/scripts/run_e2e_from_limitation.sh" >> "$ROOT/logs/v14b/e2e_continue_nohup.log" 2>&1 &
  else
    log "启动主流程: run_e2e_continue (scibert→report)"
    nohup bash "$ROOT/scripts/run_e2e_continue.sh" >> "$ROOT/logs/v14b/e2e_continue_nohup.log" 2>&1 &
  fi
  sleep 3
}

start_enrich() {
  log "启动 Step1 enrich 补齐"
  nohup bash "$ROOT/scripts/run_step1_arxiv_enrich.sh" >> "$ROOT/logs/v14b/step1_arxiv_nohup.log" 2>&1 &
  sleep 3
}

log "========== 双任务监控启动 (间隔 ${INTERVAL}s) =========="

while true; do
  pending=$(pending_enrich)
  cks=$(ls -1 reports/v14b_pilot/checkpoints/*.done.json 2>/dev/null | wc -l | tr -d ' ')

  if reports_done; then
    log "主流程报告已完成; enrich 待处理=${pending}"
    if [[ "$pending" -eq 0 ]] || enrich_running; then
      [[ "$pending" -eq 0 ]] && log "enrich 也已补齐，监控退出" && exit 0
    else
      start_enrich
    fi
  else
    log "检查: ck=$cks enrich待处理=$pending e2e=$(e2e_running && echo yes || echo no) enrich=$(enrich_running && echo yes || echo no)"
    if ! e2e_running; then
      log "主流程未运行，尝试启动"
      start_e2e
    fi
    if [[ "$pending" -gt 0 ]] && ! enrich_running; then
      log "enrich 未运行且仍有 ${pending} 篇，启动补齐"
      start_enrich
    fi
  fi

  sleep "$INTERVAL"
done
