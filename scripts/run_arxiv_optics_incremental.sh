#!/usr/bin/env bash
# 仅抓取 HWM 之后的新论文 (不 --refresh, 不指定 --from)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ARXIV_FROM=
export HARVEST_REFRESH=false
exec bash "$ROOT/scripts/run_arxiv_optics_harvest.sh"
