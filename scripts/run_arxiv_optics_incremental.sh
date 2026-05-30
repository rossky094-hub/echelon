#!/usr/bin/env bash
# LEGACY compatibility: old arXiv optics incremental harvest.
# Not current V14B decision workflow; prefer product-chain/post-frontfill-chain.
#
# 仅抓取 HWM 之后的新论文 (不 --refresh, 不指定 --from)
set -euo pipefail
if [[ "${V14B_RUN_LEGACY_ARXIV_FLOW:-0}" != "1" ]]; then
  echo "LEGACY compatibility script: old arXiv gap-first flow is not the current V14B decision workflow."
  echo "Set V14B_RUN_LEGACY_ARXIV_FLOW=1 to run it intentionally; otherwise use make product-chain or make post-frontfill-chain."
  exit 2
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ARXIV_FROM=
export HARVEST_REFRESH=false
exec bash "$ROOT/scripts/run_arxiv_optics_harvest.sh"
