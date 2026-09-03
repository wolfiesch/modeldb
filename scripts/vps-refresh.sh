#!/usr/bin/env bash
set -euo pipefail

MODELDB_REPO=${MODELDB_REPO:-$(cd "$(dirname "$0")/.." && pwd)}
STATIC_DIR=${STATIC_DIR:-/srv/agent-webhook-hub/static/models}

cd "$MODELDB_REPO"
QUALITY_REPORT_PATH=${QUALITY_REPORT_PATH:-"$MODELDB_REPO/.perf/quality-gates/latest.json"}
REFRESH_STATUS_PATH=${REFRESH_STATUS_PATH:-"$MODELDB_REPO/dashboard/public/data/refresh-status.json"}
mkdir -p "$(dirname "$QUALITY_REPORT_PATH")" "$(dirname "$REFRESH_STATUS_PATH")"

quality_baseline=$(mktemp "${TMPDIR:-/tmp}/modeldb-quality-baseline.XXXXXX.sqlite")
pipeline_log=$(mktemp "${TMPDIR:-/tmp}/modeldb-pipeline.XXXXXX.log")
trap 'rm -f "$quality_baseline" "$pipeline_log"' EXIT
quality_baseline_args=()
if [[ -f db/modeldb.sqlite ]]; then
  cp db/modeldb.sqlite "$quality_baseline"
  quality_baseline_args=(--baseline "$quality_baseline")
fi

pipeline_status=ok
tps_status=skipped
gates_status=skipped
if ! python3 -m store.pipeline >"$pipeline_log" 2>&1; then
  pipeline_status=failed
  cat "$pipeline_log" >&2
fi

if [[ "$pipeline_status" == ok ]]; then
  # TPS collection is paid enrichment, not a publish gate: a dead selector or an
  # exhausted provider balance must never freeze the live dashboard data.
  tps_status=ok
  if ! OMP_TPS_ALLOW_PAID=${OMP_TPS_ALLOW_PAID:-0} python3 scripts/collect_omp_tps.py --config scripts/omp_tps_models.json --runs "${OMP_TPS_RUNS:-3}" --timeout "${OMP_TPS_TIMEOUT:-120}"; then
    tps_status=failed
    echo "warning: OMP TPS collection failed; publishing with the previously stored TPS samples" >&2
  fi

  gates_status=ok
  if ! python3 -m store.quality_gates --db db/modeldb.sqlite "${quality_baseline_args[@]}" --report-file "$QUALITY_REPORT_PATH"; then
    gates_status=blocked
  fi
fi

# Machine-readable staleness record. On success it is published with the data;
# when a refresh dies earlier, the live copy's generatedAt goes stale, which is
# itself the failure signal for the site.
python3 - "$pipeline_log" "$REFRESH_STATUS_PATH" "$pipeline_status" "$tps_status" "$gates_status" "$QUALITY_REPORT_PATH" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

pipeline_log, status_path = sys.argv[1], sys.argv[2]
pipeline_status, tps_status, gates_status = sys.argv[3:6]
quality_report_path = Path(sys.argv[6])

sources = {}
stages = {
    "pipeline": pipeline_status,
    "tps_collection": tps_status,
    "quality_gates": gates_status,
}
for line in Path(pipeline_log).read_text(encoding="utf-8", errors="replace").splitlines():
    if ": " not in line:
        continue
    stage, value = line.split(": ", 1)
    if stage == "ingest":
        inner = value.strip()
        if inner.startswith("[") and inner.endswith("]"):
            inner = inner[1:-1]
        for entry in inner.split("', '"):
            entry = entry.strip().strip("'").strip('"')
            if not entry or ":" not in entry:
                continue
            source = entry.split(":", 1)[0].strip()
            if ": FAILED (" in entry:
                sources[source] = "failed"
            elif ": unavailable (" in entry:
                sources[source] = "unavailable"
            else:
                sources[source] = "ok"
    elif stage not in stages:
        stages[stage] = value

try:
    quality = json.loads(quality_report_path.read_text(encoding="utf-8"))
    summary = quality.get("summary") or {}
    quality_summary = {
        "blocked": bool(quality.get("blocked")),
        "errors": summary.get("errors"),
        "warnings": summary.get("warnings"),
    }
except (OSError, ValueError):
    quality_summary = {"blocked": gates_status == "blocked", "errors": None, "warnings": None}

status = {
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "pipeline": pipeline_status,
    "tpsCollection": tps_status,
    "qualityGates": quality_summary,
    "stages": stages,
    "sources": sources,
}
Path(status_path).write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

if [[ "$pipeline_status" != ok || "$gates_status" == blocked ]]; then
  echo "refresh aborted: pipeline=$pipeline_status quality_gates=$gates_status (details: $QUALITY_REPORT_PATH)" >&2
  exit 1
fi

bun dashboard/scripts/extract.mjs
rsync -av --delete dashboard/public/data/ "$STATIC_DIR/data/"
