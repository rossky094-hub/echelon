#!/usr/bin/env bash
# End-to-end daemon for V14B optics:
# 1) finish the current Step1 enrich first
# 2) optionally close the arXiv gap list when explicitly requested
# 3) quiesce legacy arXiv monitors/harvesters after enrich
# 4) run graph-ready repair + clean pilot graph rerun
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs/v14b reports/v14b_pilot/checkpoints

DB="${ECHELON_LIBRARY_DB:-$ROOT/db/echelon_library.sqlite3}"
LOG="$ROOT/logs/v14b/monitor_optics_full_pipeline.log"
DIFF_LOG="$ROOT/logs/v14b/diff_arxiv_optics_monthly.log"
MISSING_FILE="$ROOT/reports/v14b_pilot/arxiv_optics_missing_ids.txt"
INTERVAL="${MONITOR_INTERVAL_SEC:-300}"
DIFF_DELAY="${ARXIV_DIFF_DELAY:-60}"
DIFF_RETRY_SLEEP="${ARXIV_DIFF_RETRY_SLEEP:-7200}"
DIFF_INITIAL_SLEEP="${ARXIV_DIFF_INITIAL_SLEEP:-0}"
MAX_GAP_ROUNDS="${MAX_GAP_ROUNDS:-20}"
REQUIRE_GAP_CLOSED="${V14B_REQUIRE_GAP_CLOSED:-0}"
STOP_LEGACY_AFTER_ENRICH="${V14B_STOP_LEGACY_AFTER_ENRICH:-1}"

S2_RPS="${V14B_S2_REQUESTS_PER_SEC:-0.25}"
S2_DELAY="${V14B_S2_DELAY:-4.2}"
S2_RETRIES="${V14B_S2_MAX_RETRIES:-6}"
ENRICH_CONCURRENCY="${V14B_ENRICH_CONCURRENCY:-2}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

sql_scalar() {
  sqlite3 -cmd ".timeout 20000" "$DB" "$1" 2>/dev/null || echo "0"
}

optics_count() {
  sql_scalar "SELECT COUNT(*) FROM papers WHERE arxiv_id IS NOT NULL AND (
    primary_topic_id LIKE '%optics%'
    OR raw_jsonb LIKE '%physics.optics%'
    OR raw_jsonb LIKE '%\"physics.optics\"%'
  );"
}

total_papers() {
  sql_scalar "SELECT COUNT(*) FROM papers;"
}

pending_enrich() {
  sql_scalar "SELECT COUNT(*) FROM papers WHERE openalex_enriched IS NULL OR openalex_enriched=0;"
}

refs_count() {
  sql_scalar "SELECT COUNT(*) FROM paper_references;"
}

linked_refs_count() {
  sql_scalar "SELECT COUNT(*) FROM paper_references WHERE cited_paper_id_internal IS NOT NULL;"
}

missing_count() {
  if [[ -s "$MISSING_FILE" ]]; then
    wc -l < "$MISSING_FILE" | tr -d ' '
  else
    echo "0"
  fi
}

prune_known_missing_file() {
  if [[ ! -s "$MISSING_FILE" ]]; then
    return
  fi
  python3 - <<PY
from pathlib import Path
import sqlite3

path = Path("$MISSING_FILE")
ids = [x.strip() for x in path.read_text().splitlines() if x.strip()]
conn = sqlite3.connect("$DB")
db_ids = {r[0] for r in conn.execute("SELECT arxiv_id FROM papers WHERE arxiv_id IS NOT NULL") if r[0]}
remaining = [x for x in ids if x not in db_ids]
if len(remaining) < len(ids):
    backup = path.with_suffix(path.suffix + ".before_prune")
    backup.write_text("\\n".join(ids) + ("\\n" if ids else ""))
    path.write_text("\\n".join(remaining) + ("\\n" if remaining else ""))
    print(f"pruned missing IDs: {len(ids)} -> {len(remaining)}")
PY
}

running_missing_fetch() {
  pgrep -f "bash scripts/fetch_missing_arxiv_optics.sh|fetch_missing_arxiv_optics.sh" 2>/dev/null | grep -v "^$$\$" || true
}

running_diff() {
  pgrep -f "scripts/diff_arxiv_optics_vs_db.py" 2>/dev/null || true
}

running_enrich() {
  pgrep -f "echelon.v14b.step1_enrich" 2>/dev/null || true
}

running_pilot() {
  pgrep -f "make pilot|echelon.v14b.step" 2>/dev/null || true
}

legacy_arxiv_pids() {
  pgrep -f "monitor_crawl_enrich_pilot.sh|run_arxiv_optics_harvest.sh|echelon.crawler.worker --provider arxiv --set physics:physics:optics" 2>/dev/null \
    | awk -v self="$$" '$1 != self' || true
}

stop_legacy_arxiv_processes() {
  local pids
  pids="$(legacy_arxiv_pids | tr '\n' ' ')"
  if [[ -z "$pids" ]]; then
    log "no legacy arXiv monitor/harvest process to stop"
    return
  fi
  log "stopping legacy arXiv monitor/harvest pids=[$pids]"
  kill $pids 2>/dev/null || true
  sleep 10
  pids="$(legacy_arxiv_pids | tr '\n' ' ')"
  if [[ -n "$pids" ]]; then
    log "force stopping lingering legacy arXiv pids=[$pids]"
    kill -9 $pids 2>/dev/null || true
  fi
}

status_line() {
  log "status optics=$(optics_count) total=$(total_papers) pending_enrich=$(pending_enrich) refs=$(refs_count) linked_refs=$(linked_refs_count) missing_file=$(missing_count)"
}

wait_for_external_fetches() {
  while [[ -n "$(running_missing_fetch)" || -n "$(running_diff)" ]]; do
    status_line
    log "waiting for active gap/fetch process pids=[$(running_missing_fetch | tr '\n' ' ')$(running_diff | tr '\n' ' ')]"
    sleep "$INTERVAL"
  done
}

run_gap_diff() {
  log "run gap diff: monthly arXiv physics.optics enumeration"
  : > "$DIFF_LOG"
  if ! python3 scripts/diff_arxiv_optics_vs_db.py \
    --db "$DB" \
    --window month \
    --delay "$DIFF_DELAY" \
    --out-dir reports/v14b_pilot \
    >> "$DIFF_LOG" 2>&1; then
    log "gap diff failed, likely API throttling; cooldown ${DIFF_RETRY_SLEEP}s before retry"
    tail -n 30 "$DIFF_LOG" | tee -a "$LOG" >/dev/null || true
    sleep "$DIFF_RETRY_SLEEP"
    return 1
  fi
  log "gap diff done: missing=$(missing_count)"
  tail -n 20 "$DIFF_LOG" | tee -a "$LOG" >/dev/null || true
}

run_s2_missing_fetch() {
  local n
  n="$(missing_count)"
  if [[ "$n" -eq 0 ]]; then
    return
  fi
  log "run S2 missing fetch: ids=$n rps=$S2_RPS delay=$S2_DELAY retries=$S2_RETRIES"
  V14B_S2_REQUESTS_PER_SEC="$S2_RPS" \
  V14B_S2_DELAY="$S2_DELAY" \
  V14B_S2_MAX_RETRIES="$S2_RETRIES" \
  MISSING_FETCH_PROVIDER=s2 \
    bash scripts/fetch_missing_arxiv_optics.sh
  log "S2 missing fetch done"
}

run_gap_until_closed() {
  local round
  for ((round=1; round<=MAX_GAP_ROUNDS; round++)); do
    wait_for_external_fetches
    status_line
    log "gap round $round/$MAX_GAP_ROUNDS"
    if ! run_gap_diff; then
      prune_known_missing_file | tee -a "$LOG" >/dev/null || true
      continue
    fi
    if [[ "$(missing_count)" -eq 0 ]]; then
      log "gap closed: no missing arXiv IDs from monthly enumeration"
      return 0
    fi
    run_s2_missing_fetch
  done
  log "gap loop stopped after MAX_GAP_ROUNDS=$MAX_GAP_ROUNDS with missing=$(missing_count)"
  return 1
}

run_enrich_until_done() {
  local pe
  while true; do
    pe="$(pending_enrich)"
    status_line
    if [[ "$pe" -eq 0 ]]; then
      log "enrich complete"
      return 0
    fi
    while [[ -n "$(running_enrich)" ]]; do
      log "waiting for active Step1 enrich pids=[$(running_enrich | tr '\n' ' ')]"
      sleep "$INTERVAL"
      status_line
    done
    log "run Step1 enrich: pending=$pe concurrency=$ENRICH_CONCURRENCY"
    V14B_S2_REQUESTS_PER_SEC="$S2_RPS" \
    V14B_S2_DELAY="$S2_DELAY" \
    V14B_S2_MAX_RETRIES="$S2_RETRIES" \
    V14B_ENRICH_CONCURRENCY="$ENRICH_CONCURRENCY" \
      bash scripts/run_step1_arxiv_enrich.sh
    sleep "$INTERVAL"
  done
}

run_quality_audit() {
  log "run quality audit"
  python3 -m echelon.v14b.step0_quality_audit \
    --db "$DB" \
    --out-dir "$ROOT/reports/v14b_pilot" \
    --fail-on fail \
    >> "$ROOT/logs/v14b/quality_audit_nohup.log" 2>&1
  log "quality audit done"
}

run_graph_prep_once() {
  while [[ -n "$(running_pilot)" ]]; do
    log "waiting for active pilot pids=[$(running_pilot | tr '\n' ' ')]"
    sleep "$INTERVAL"
  done
  log "run graph prep: id-repair + graph-features + embeddings"
  make graph-prep >> "$ROOT/logs/v14b/make_pilot_full.log" 2>&1
  log "graph prep done"
}

run_pilot_once() {
  while [[ -n "$(running_pilot)" ]]; do
    log "waiting for active pilot pids=[$(running_pilot | tr '\n' ' ')]"
    sleep "$INTERVAL"
  done
  log "run graph-ready repair + clean graph rerun: pilot-graph"
  make pilot-graph >> "$ROOT/logs/v14b/make_pilot_full.log" 2>&1
  log "make pilot-graph done"
  log "run visual graph product layer: visual-graph"
  make visual-graph >> "$ROOT/logs/v14b/make_pilot_full.log" 2>&1
  log "make visual-graph done"
}

log "========== monitor_optics_full_pipeline start interval=${INTERVAL}s require_gap_closed=${REQUIRE_GAP_CLOSED} =========="
status_line

if [[ "$DIFF_INITIAL_SLEEP" -gt 0 && "$REQUIRE_GAP_CLOSED" == "1" ]]; then
  log "initial arXiv diff cooldown ${DIFF_INITIAL_SLEEP}s"
  sleep "$DIFF_INITIAL_SLEEP"
fi

run_enrich_until_done

if [[ "$STOP_LEGACY_AFTER_ENRICH" == "1" ]]; then
  stop_legacy_arxiv_processes
fi

if [[ "$REQUIRE_GAP_CLOSED" == "1" ]]; then
  run_gap_until_closed || log "gap not fully closed; continuing with graph rerun by policy"
else
  prune_known_missing_file | tee -a "$LOG" >/dev/null || true
  log "skip arXiv gap closure before graph rerun by policy: missing_file=$(missing_count)"
fi

run_pilot_once

status_line
log "========== monitor_optics_full_pipeline complete =========="
