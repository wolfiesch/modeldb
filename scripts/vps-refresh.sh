#!/usr/bin/env bash
set -euo pipefail

MODELDB_REPO=${MODELDB_REPO:-$(cd "$(dirname "$0")/.." && pwd)}
STATIC_DIR=${STATIC_DIR:-/srv/agent-webhook-hub/static/models}

cd "$MODELDB_REPO"
QUALITY_REPORT_PATH=${QUALITY_REPORT_PATH:-"$MODELDB_REPO/.perf/quality-gates/latest.json"}
mkdir -p "$(dirname "$QUALITY_REPORT_PATH")"

quality_baseline=$(mktemp "${TMPDIR:-/tmp}/modeldb-quality-baseline.XXXXXX.sqlite")
trap 'rm -f "$quality_baseline"' EXIT
quality_baseline_args=()
if [[ -f db/modeldb.sqlite ]]; then
  cp db/modeldb.sqlite "$quality_baseline"
  quality_baseline_args=(--baseline "$quality_baseline")
fi

python3 -m store.pipeline
OMP_TPS_ALLOW_PAID=${OMP_TPS_ALLOW_PAID:-0} python3 scripts/collect_omp_tps.py --config scripts/omp_tps_models.json --runs "${OMP_TPS_RUNS:-3}" --timeout "${OMP_TPS_TIMEOUT:-120}"
python3 -m store.quality_gates --db db/modeldb.sqlite "${quality_baseline_args[@]}" --report-file "$QUALITY_REPORT_PATH"
bun dashboard/scripts/extract.mjs
rsync -av --delete dashboard/public/data/ "$STATIC_DIR/data/"
