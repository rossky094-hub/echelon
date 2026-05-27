#!/usr/bin/env bash
# 等 arxiv search 爬虫结束 → 清 checkpoint → make pilot
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs/v14b reports/v14b_pilot/checkpoints

LOG="$ROOT/logs/v14b/wait_harvest_then_pilot.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "等待 arxiv worker 结束..."
while pgrep -f "echelon.crawler.worker.*arxiv" >/dev/null 2>&1; do
  sleep 300
  n=$(sqlite3 "$ROOT/db/echelon_library.sqlite3" "SELECT COUNT(*) FROM papers;" 2>/dev/null || echo "?")
  log "爬虫仍在运行, papers=$n"
done

log "爬虫已停止"
if [[ -f "$ROOT/db/v14_pilot.sqlite3" ]]; then
  cp "$ROOT/db/v14_pilot.sqlite3" "$ROOT/db/v14_pilot.sqlite3.bak.$(date +%Y%m%d%H%M)"
fi
rm -f "$ROOT/reports/v14b_pilot/checkpoints/"*.done.json 2>/dev/null || true

log "启动 make pilot"
set -a && [[ -f .env ]] && source .env && set +a
make pilot >> "$ROOT/logs/v14b/make_pilot_full.log" 2>&1
log "make pilot 结束 exit=$?"
