#!/usr/bin/env bash
# 后台单独跑 Step1: 补全 physics.optics 库内未 enrich 的论文 (含纯 arXiv)
# 与 Step5c+ 并行: 共用 echelon_library.sqlite3 (WAL), 不碰 v14_pilot.sqlite3
#
# 用法:
#   nohup bash scripts/run_step1_arxiv_enrich.sh >> logs/v14b/step1_arxiv_nohup.log 2>&1 &
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs/v14b

LOG="$ROOT/logs/v14b/step1_arxiv_enrich.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

assert_v14b_imports() {
  python3 - "$ROOT" <<'PY'
import importlib.util
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
mods = [
    "echelon.v14b.step1_enrich",
    "echelon.v14b.enrich_providers",
    "echelon.v14b.config",
]
bad = []
for mod in mods:
    spec = importlib.util.find_spec(mod)
    origin = Path(spec.origin).resolve() if spec and spec.origin else None
    print(f"{mod}: {origin}")
    if origin is None:
        bad.append(f"{mod}: missing")
    elif root not in origin.parents:
        bad.append(f"{mod}: {origin}")
if bad:
    print("ERROR: V14B import path mismatch; refusing to run Step1 enrich.", file=sys.stderr)
    for item in bad:
        print(f"  {item}", file=sys.stderr)
    sys.exit(2)
PY
}

if pgrep -f "echelon.v14b.step1_enrich" >/dev/null 2>&1; then
  log "已有 step1_enrich 进程在跑, 退出避免重复"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

# 与 E2E 并行时建议: S2 1req/s, 低并发, 不启用 OpenAlex 避免 429
export V14B_ENRICH_PROVIDERS="${V14B_ENRICH_PROVIDERS:-s2,crossref}"
export V14B_USE_OPENALEX="${V14B_USE_OPENALEX:-false}"
export V14B_CONCURRENCY="${V14B_ENRICH_CONCURRENCY:-2}"
export V14B_S2_DELAY="${V14B_ENRICH_S2_DELAY:-1.05}"

PENDING=$(sqlite3 "$ROOT/db/echelon_library.sqlite3" \
  "SELECT COUNT(*) FROM papers WHERE openalex_enriched IS NULL OR openalex_enriched=0;" 2>/dev/null || echo "?")

log "========== Step1 增量 enrich (physics.optics 库) =========="
log "待处理: ${PENDING} 篇 | providers=${V14B_ENRICH_PROVIDERS} | concurrency=${V14B_CONCURRENCY} | s2_delay=${V14B_S2_DELAY}s"
log "校验 V14B import 来源..."
assert_v14b_imports >> "$LOG" 2>&1

# --no-resume: 忽略「整步已完成」checkpoint, 仍跳过 openalex_enriched=1 的篇目
python3 -m echelon.v14b.step1_enrich \
  --db "$ROOT/db/echelon_library.sqlite3" \
  --concurrency "$V14B_CONCURRENCY" \
  --no-resume \
  >> "$LOG" 2>&1

log "========== Step1 enrich 结束 =========="
