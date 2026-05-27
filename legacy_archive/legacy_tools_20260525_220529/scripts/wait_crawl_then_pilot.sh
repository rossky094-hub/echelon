#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LOG="$ROOT/logs/v14b/wait_crawl_then_pilot.log"
HARVEST_LOG="$ROOT/logs/v14b/arxiv_optics_harvest.log"
PILOT_LOG="$ROOT/logs/v14b/make_pilot_full.log"
MARKER="$ROOT/logs/v14b/.crawl_wait_marker_ts"
mkdir -p logs/v14b

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

# Wait for crawl started at or after this marker (current full run)
if [[ ! -f "$MARKER" ]]; then
  date '+%Y-%m-%d %H:%M:%S' > "$MARKER"
fi
WAIT_AFTER=$(cat "$MARKER")
log "Waiting for arxiv worker to finish (after $WAIT_AFTER)"

MAX_ITER=288  # 24h @ 5min
RESTARTED=0
for ((i=1; i<=MAX_ITER; i++)); do
  if pgrep -f "echelon.crawler.worker.*arxiv" >/dev/null 2>&1; then
    tail -1 "$HARVEST_LOG" 2>/dev/null | log "crawler running: $(cat)" || true
    sleep 300
    continue
  fi
  # worker gone — check completion in harvest log after marker
  if awk -v after="$WAIT_AFTER" '
    /========== 抓取结束 ==========/ { end=$0; got=1 }
    END { if (got) print end; else exit 1 }
  ' "$HARVEST_LOG" 2>/dev/null | grep -q .; then
    log "Crawler finished (抓取结束 in log)"
    break
  fi
  if grep -q "摄入完成" "$HARVEST_LOG" 2>/dev/null; then
    last=$(grep "摄入完成" "$HARVEST_LOG" | tail -1)
    log "Worker exited with stats: $last"
    break
  fi
  log "Worker died without clear completion"
  if [[ $RESTARTED -lt 1 ]]; then
    log "Restarting harvest once"
    nohup bash scripts/run_arxiv_optics_harvest.sh >> "$HARVEST_LOG" 2>&1 &
    RESTARTED=1
    sleep 30
    continue
  fi
  log "Restart limit reached; aborting wait"
  exit 2
done

if pgrep -f "echelon.crawler.worker.*arxiv" >/dev/null 2>&1; then
  log "Timeout 24h with crawler still running"
  exit 3
fi

PAPERS=$(sqlite3 db/echelon_library.sqlite3 "SELECT COUNT(*) FROM papers;" 2>/dev/null || echo "?")
log "Library paper count: $PAPERS"

# Prep pilot
if [[ -f db/v14_pilot.sqlite3 ]]; then
  cp -f db/v14_pilot.sqlite3 "db/v14_pilot.sqlite3.bak.$(date +%Y%m%d)"
  log "Backed up v14_pilot.sqlite3"
fi
rm -f reports/v14b_pilot/checkpoints/*.done.json
log "Cleared pilot checkpoints"

pkill -f monitor_e2e_pilot.sh 2>/dev/null || true
pgrep -fl "make pilot" && { log "make pilot already running"; exit 4; } || true

source .env 2>/dev/null || true
log "Starting make pilot"
nohup make pilot >> "$PILOT_LOG" 2>&1 &
PILOT_PID=$!
log "make pilot pid=$PILOT_PID"

# Monitor checkpoints
while kill -0 $PILOT_PID 2>/dev/null; do
  ls reports/v14b_pilot/checkpoints/*.done.json 2>/dev/null | wc -l | xargs -I{} log "checkpoints done: {}"
  sleep 300
done
wait $PILOT_PID 2>/dev/null || EC=$?
log "make pilot exited code=${EC:-0}"

# Verify reports
for f in reports/v14b_pilot/V14B_Pilot_算法验证报告.md reports/v14b_pilot/未来方向预测_交集报告.md; do
  if [[ -f "$f" ]]; then
    sz=$(wc -c < "$f" | tr -d ' ')
    log "Report $f size=$sz bytes"
  else
    log "MISSING $f"
  fi
done
FD=$(sqlite3 db/v14_pilot.sqlite3 "SELECT COUNT(*) FROM future_directions;" 2>/dev/null || echo "?")
log "future_directions rows: $FD"
log "DONE"
