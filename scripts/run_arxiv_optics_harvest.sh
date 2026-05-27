#!/usr/bin/env bash
# arXiv physics.optics 全量抓取 → echelon_library.sqlite3
#
# 重要: OAI set physics:physics:optics 仅 ~1.3 万篇 (主分类归档)
#       search API cat:physics.optics 含交叉分类, 约 5.6 万+ 篇 (默认)
#
# 与 Step1 enrich 区别:
#   - 本脚本: 从 arXiv 拉元数据 (title/abstract/authors/categories/doi/raw_jsonb)
#   - Step1:  在已有论文上补 S2/Crossref 引用与 cited_by_count
#
# 用法:
#   nohup bash scripts/run_arxiv_optics_harvest.sh >> logs/v14b/arxiv_harvest_nohup.log 2>&1 &
#
#   # 仅 OAI set (~1.3万, 不推荐)
#   ARXIV_MODE=oai bash scripts/run_arxiv_optics_harvest.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs/v14b

LOG="${ARXIV_HARVEST_LOG:-$ROOT/logs/v14b/arxiv_optics_harvest.log}"
DB="${ARXIV_DB:-$ROOT/db/echelon_library.sqlite3}"
SET="${ARXIV_SET:-physics:physics:optics}"
MODE="${ARXIV_MODE:-search}"
FULL="${ARXIV_FULL:-true}"
FROM="${ARXIV_FROM:-}"
CURSOR_FILE="${ARXIV_CURSOR_FILE:-$ROOT/logs/v14b/arxiv_harvest_cursor.json}"
if [[ -z "$FROM" && -f "$CURSOR_FILE" ]]; then
  FROM="$(python3 -c "import json; print(json.load(open('$CURSOR_FILE')).get('resume_from',''))" 2>/dev/null || true)"
fi
TO="${ARXIV_TO:-$(date +%Y-%m-%d)}"
BACKFILL="${ARXIV_BACKFILL:-false}"
if [[ -f "$CURSOR_FILE" ]]; then
  if [[ "$BACKFILL" != "true" ]]; then
    BACKFILL="$(python3 -c "import json; c=json.load(open('$CURSOR_FILE')); print('true' if c.get('backfill_mode') or c.get('date_crawl_complete') else 'false')" 2>/dev/null || echo false)"
  fi
fi
if [[ -n "$FROM" && "$FROM" > "$TO" ]]; then
  BACKFILL=true
  FROM=""
fi
if [[ "$MODE" == "search" ]]; then
  DELAY="${ARXIV_DELAY:-10}"
else
  DELAY="${ARXIV_DELAY:-3.0}"
fi
REFRESH="${HARVEST_REFRESH:-true}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

if pgrep -f "echelon.crawler.worker.*arxiv" >/dev/null 2>&1; then
  log "已有 arxiv worker 在跑, 退出"
  exit 1
fi

EXTRA=(--mode "$MODE")
if [[ "$REFRESH" == "true" ]]; then
  EXTRA+=(--refresh)
fi
if [[ "$BACKFILL" == "true" && "$MODE" == "search" ]]; then
  EXTRA+=(--backfill)
elif [[ -n "$FROM" ]]; then
  EXTRA+=(--from "$FROM" --to "$TO")
elif [[ "$FULL" == "true" ]]; then
  EXTRA+=(--full)
fi

log "========== arXiv optics 全量抓取 =========="
log "set=$SET mode=$MODE (~56228 if search) full=$FULL backfill=$BACKFILL refresh=$REFRESH delay=${DELAY}s db=$DB"

python3 -m echelon.crawler.worker --provider arxiv --set "$SET" \
  --delay "$DELAY" --db "$DB" --stats "${EXTRA[@]}" >> "$LOG" 2>&1

log "========== 抓取结束 =========="
