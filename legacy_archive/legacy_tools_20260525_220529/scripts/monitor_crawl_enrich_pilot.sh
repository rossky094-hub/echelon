#!/usr/bin/env bash
# Daemon: crawl until optics>=56000, enrich until pending=0, then make pilot.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs/v14b reports/v14b_pilot/checkpoints

DB="${ECHELON_LIBRARY_DB:-$ROOT/db/echelon_library.sqlite3}"
LOG="$ROOT/logs/v14b/monitor_crawl_enrich_pilot.log"
HARVEST_LOG="$ROOT/logs/v14b/arxiv_optics_harvest.log"
CURSOR_FILE="$ROOT/logs/v14b/arxiv_harvest_cursor.json"
STEP1_CKPT="$ROOT/reports/v14b_pilot/checkpoints/step1_enrich.done.json"
INTERVAL="${MONITOR_INTERVAL_SEC:-300}"
CRAWL_TARGET="${CRAWL_TARGET_COUNT:-56251}"  # arXiv API cat:physics.optics totalResults (2026-05)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

optics_count() {
  sqlite3 "$DB" "SELECT COUNT(*) FROM papers WHERE arxiv_id IS NOT NULL AND (
    primary_topic_id LIKE '%optics%'
    OR raw_jsonb LIKE '%physics.optics%'
    OR raw_jsonb LIKE '%\"physics.optics\"%'
  );" 2>/dev/null || echo "0"
}

total_papers() {
  sqlite3 "$DB" "SELECT COUNT(*) FROM papers;" 2>/dev/null || echo "0"
}

pending_enrich() {
  sqlite3 "$DB" "SELECT COUNT(*) FROM papers WHERE openalex_enriched IS NULL OR openalex_enriched=0;" 2>/dev/null || echo "0"
}

arxiv_workers() {
  pgrep -f "echelon.crawler.worker.*arxiv" 2>/dev/null || true
}

enrich_running() {
  pgrep -f "echelon.v14b.step1_enrich" 2>/dev/null || true
}

pilot_running() {
  pgrep -f "make pilot" 2>/dev/null || true
  pgrep -f "echelon.v14b" 2>/dev/null | head -1 || true
}

kill_arxiv_workers() {
  local pids
  pids=$(arxiv_workers)
  if [[ -n "$pids" ]]; then
    log "停止 arxiv worker: $pids"
    kill $pids 2>/dev/null || true
    sleep 3
    pids=$(arxiv_workers)
    if [[ -n "$pids" ]]; then
      kill -9 $pids 2>/dev/null || true
    fi
  fi
}

dedupe_arxiv_workers() {
  local pids=($(arxiv_workers))
  if [[ ${#pids[@]} -gt 1 ]]; then
    log "发现多个 arxiv worker (${pids[*]}), 保留第一个"
    for ((i=1; i<${#pids[@]}; i++)); do kill "${pids[$i]}" 2>/dev/null || true; done
  fi
}

resume_from() {
  if [[ -n "${ARXIV_FROM:-}" ]]; then
    echo "$ARXIV_FROM"
    return
  fi
  if [[ -f "$CURSOR_FILE" ]]; then
    python3 -c "import json; print(json.load(open('$CURSOR_FILE')).get('resume_from',''))" 2>/dev/null || true
    return
  fi
  echo "2004-12-01"
}

cursor_wants_backfill() {
  if [[ "${ARXIV_BACKFILL:-}" == "true" ]]; then
    return 0
  fi
  if [[ ! -f "$CURSOR_FILE" ]]; then
    return 1
  fi
  python3 -c "
import json
from datetime import date
c=json.load(open('$CURSOR_FILE'))
today=date.today().isoformat()
rf=c.get('resume_from','')
if c.get('backfill_mode') or c.get('date_crawl_complete'):
    exit(0)
if rf and rf > today:
    exit(0)
exit(1)
" 2>/dev/null
}

diagnose_harvest() {
  log "--- harvest log (last 50 lines) ---"
  tail -n 50 "$HARVEST_LOG" 2>/dev/null | tee -a "$LOG" || log "(no harvest log)"
}

start_harvest() {
  local from
  from=$(resume_from)
  if cursor_wants_backfill; then
    log "cursor 日期 crawl 已完成或 resume 在未来, 启动 backfill (无 --from)"
    from="(backfill)"
    ARXIV_MODE=search ARXIV_DELAY="${ARXIV_DELAY:-10}" HARVEST_REFRESH=true       ARXIV_FULL=false ARXIV_BACKFILL=true       nohup bash "$ROOT/scripts/run_arxiv_optics_harvest.sh" >> "$ROOT/logs/v14b/arxiv_harvest_nohup.log" 2>&1 &
  else
    log "启动 arxiv harvest: mode=search delay=10 from=$from refresh=true"
    ARXIV_MODE=search ARXIV_DELAY="${ARXIV_DELAY:-10}" HARVEST_REFRESH=true       ARXIV_FULL=false ARXIV_FROM="$from"       nohup bash "$ROOT/scripts/run_arxiv_optics_harvest.sh" >> "$ROOT/logs/v14b/arxiv_harvest_nohup.log" 2>&1 &
  fi
  log "harvest nohup pid=$!"
}

maybe_fix_enrich_env() {
  if [[ ! -f "$ROOT/.env" ]]; then
    return
  fi
  if grep -q "429\|rate limit\|RateLimit\|Too Many" "$ROOT/logs/v14b/step1_arxiv_enrich.log" 2>/dev/null; then
    log "enrich 日志含限流, 建议低并发 (已在启动时 export V14B_CONCURRENCY=2)"
    export V14B_ENRICH_CONCURRENCY="${V14B_ENRICH_CONCURRENCY:-2}"
    export V14B_CONCURRENCY="${V14B_CONCURRENCY:-2}"
  fi
}

start_enrich() {
  if [[ -f "$STEP1_CKPT" ]]; then
    log "移除 stale step1 checkpoint (全库 enrich)"
    rm -f "$STEP1_CKPT"
  fi
  maybe_fix_enrich_env
  log "启动 step1 enrich"
  nohup bash "$ROOT/scripts/run_step1_arxiv_enrich.sh" >> "$ROOT/logs/v14b/step1_arxiv_nohup.log" 2>&1 &
  log "enrich nohup pid=$!"
}

start_pilot() {
  log "清理 pilot checkpoints (保留 step2 代码不改动)"
  rm -f "$ROOT/reports/v14b_pilot/checkpoints/"*.done.json 2>/dev/null || true
  set -a
  # shellcheck disable=SC1091
  [[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
  set +a
  log "启动 make pilot (后台)"
  nohup make pilot >> "$ROOT/logs/v14b/make_pilot_full.log" 2>&1 &
  log "make pilot pid=$!"
}

PHASE="${MONITOR_PHASE:-A}"
log "========== monitor_crawl_enrich_pilot 启动 phase=$PHASE interval=${INTERVAL}s target=$CRAWL_TARGET =========="

while true; do
  oc=$(optics_count)
  tp=$(total_papers)
  pe=$(pending_enrich)
  log "status phase=$PHASE optics=$oc total=$tp pending_enrich=$pe arxiv_pids=[$(arxiv_workers | tr '\n' ' ')]"

  if [[ "$PHASE" == "A" ]]; then
    if [[ "$oc" -ge "$CRAWL_TARGET" ]]; then
      log "crawl target met (optics=$oc >= $CRAWL_TARGET)"
      kill_arxiv_workers
      PHASE=B
      log "进入 Phase B — enrich"
      sleep "$INTERVAL"
      continue
    fi
    if [[ "$oc" -lt "$CRAWL_TARGET" ]] && cursor_wants_backfill; then
      export ARXIV_BACKFILL=true
    fi
    dedupe_arxiv_workers
    if [[ -z "$(arxiv_workers)" ]]; then
      diagnose_harvest
      start_harvest
    fi
  elif [[ "$PHASE" == "B" ]]; then
    kill_arxiv_workers 2>/dev/null || true
    if [[ "$pe" -eq 0 ]]; then
      log "enrich complete (pending=0)"
      PHASE=C
      log "进入 Phase C — pilot"
      sleep "$INTERVAL"
      continue
    fi
    if [[ -z "$(enrich_running)" ]]; then
      if tail -n 30 "$ROOT/logs/v14b/step1_arxiv_enrich.log" 2>/dev/null | grep -qiE "error|traceback|failed"; then
        log "enrich 可能失败, 诊断 tail step1 log"
        tail -n 20 "$ROOT/logs/v14b/step1_arxiv_enrich.log" | tee -a "$LOG" || true
      fi
      start_enrich
    fi
  elif [[ "$PHASE" == "C" ]]; then
    if [[ "$oc" -lt "$CRAWL_TARGET" || "$pe" -gt 0 ]]; then
      log "前置条件不满足, 回到 Phase A/B (optics=$oc pending=$pe)"
      PHASE=A
      sleep "$INTERVAL"
      continue
    fi
    if [[ -z "$(pilot_running)" ]]; then
      if [[ -f "$ROOT/logs/v14b/make_pilot_full.log" ]] && tail -n 5 "$ROOT/logs/v14b/make_pilot_full.log" | grep -q "make pilot 结束\|Pilot complete\|ERROR"; then
        log "make pilot 似乎已结束, 见 logs/v14b/make_pilot_full.log"
        tail -n 30 "$ROOT/logs/v14b/make_pilot_full.log" | tee -a "$LOG" || true
        log "monitor 完成, 退出"
        exit 0
      fi
      start_pilot
    else
      if tail -n 3 "$ROOT/logs/v14b/make_pilot_full.log" 2>/dev/null | grep -qiE "error|failed|NetworkXError"; then
        log "make pilot 日志有错误 (step2 可能失败 — 预期内)"
      fi
    fi
  fi

  sleep "$INTERVAL"
done
