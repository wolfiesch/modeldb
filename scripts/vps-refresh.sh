#!/usr/bin/env bash
set -euo pipefail

MODELDB_REPO=${MODELDB_REPO:-$(cd "$(dirname "$0")/.." && pwd)}
STATIC_DIR=${STATIC_DIR:-/srv/static/models}

cd "$MODELDB_REPO"
python3 -m store.pipeline
OMP_TPS_ALLOW_PAID=${OMP_TPS_ALLOW_PAID:-0} python3 scripts/collect_omp_tps.py --config scripts/omp_tps_models.json --runs "${OMP_TPS_RUNS:-3}" --timeout "${OMP_TPS_TIMEOUT:-120}"
bun dashboard/scripts/extract.mjs
rsync -av --delete dashboard/public/data/ "$STATIC_DIR/data/"
