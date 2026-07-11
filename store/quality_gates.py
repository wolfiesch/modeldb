"""Read-only integrity checks for the ModelDB publish pipeline."""
from __future__ import annotations

import argparse
import json
from contextlib import closing
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

from ingest.base import DB_PATH, REPO_ROOT

DEFAULT_THRESHOLDS = {"max_benchmark_result_drop_ratio": 0.5}


def run_checks(
    db_path: str | Path = DB_PATH,
    *,
    baseline_path: str | Path | None = None,
    thresholds: dict[str, float] | None = None,
    raw_root: str | Path = REPO_ROOT,
) -> dict[str, Any]:
    """Return a deterministic quality report without modifying either database."""
    target_path = Path(db_path)
    resolved_thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    issues = _integrity_issues(target_path, Path(raw_root))
    with closing(_read_only_connection(target_path)) as conn:
        counts = _result_counts(conn)

    if baseline_path is not None:
        baseline_issues = _integrity_issues(Path(baseline_path), Path(raw_root))
        baseline_error_signatures = {
            _issue_signature(issue) for issue in baseline_issues if issue["severity"] == "error"
        }
        for issue in issues:
            if issue["severity"] == "error" and _issue_signature(issue) in baseline_error_signatures:
                issue["severity"] = "warning"
                issue["details"]["preexisting"] = True
        with closing(_read_only_connection(Path(baseline_path))) as baseline_conn:
            baseline_counts = _result_counts(baseline_conn)
        _append_count_regressions(counts, baseline_counts, resolved_thresholds, issues)
    else:
        baseline_counts = None

    errors = sum(issue["severity"] == "error" for issue in issues)
    warnings = sum(issue["severity"] == "warning" for issue in issues)
    return {
        "database": str(target_path),
        "baseline": str(baseline_path) if baseline_path is not None else None,
        "thresholds": resolved_thresholds,
        "counts": counts,
        "baseline_counts": baseline_counts,
        "issues": issues,
        "summary": {"errors": errors, "warnings": warnings},
        "blocked": errors > 0,
    }


def _read_only_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)

def _integrity_issues(db_path: Path, raw_root: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    with closing(_read_only_connection(db_path)) as conn:
        _append_orphan_benchmark_references(conn, issues)
        _append_missing_benchmark_provenance(conn, issues)
        _append_duplicate_canonical_slugs(conn, issues)
        _append_overlapping_price_intervals(conn, issues)
        _append_missing_snapshot_payloads(conn, issues, raw_root)
        _append_missing_eval_conditions(conn, issues)
    return issues


def _issue_signature(issue: dict[str, Any]) -> str:
    details = dict(issue["details"])
    details.pop("result_id", None)
    details.pop("first_price_component_id", None)
    details.pop("second_price_component_id", None)
    details.pop("snapshot_id", None)
    details.pop("preexisting", None)
    return json.dumps({"code": issue["code"], "details": details}, sort_keys=True, separators=(",", ":"))


def _append_orphan_benchmark_references(conn: sqlite3.Connection, issues: list[dict[str, Any]]) -> None:
    rows = conn.execute(
        """
        SELECT br.id, br.model_id, br.benchmark_id
        FROM benchmark_result AS br
        LEFT JOIN model AS m ON m.id = br.model_id
        LEFT JOIN benchmark AS b ON b.id = br.benchmark_id
        WHERE (br.model_id IS NOT NULL AND m.id IS NULL)
           OR (br.benchmark_id IS NOT NULL AND b.id IS NULL)
        ORDER BY br.id
        """
    )
    for result_id, model_id, benchmark_id in rows:
        _error(issues, "orphan_benchmark_reference", result_id=result_id, model_id=model_id, benchmark_id=benchmark_id)


def _append_missing_benchmark_provenance(conn: sqlite3.Connection, issues: list[dict[str, Any]]) -> None:
    rows = conn.execute(
        """
        SELECT br.id
        FROM benchmark_result AS br
        LEFT JOIN source_snapshot AS ss ON ss.id = br.source_snapshot_id
        WHERE br.source_snapshot_id IS NULL
           OR ss.id IS NULL
           OR TRIM(COALESCE(ss.url, '')) = ''
        ORDER BY br.id
        """
    )
    for (result_id,) in rows:
        _error(issues, "missing_benchmark_provenance", result_id=result_id)


def _append_duplicate_canonical_slugs(conn: sqlite3.Connection, issues: list[dict[str, Any]]) -> None:
    rows = conn.execute(
        """
        SELECT canonical_slug, GROUP_CONCAT(id, ','), COUNT(*)
        FROM model
        GROUP BY canonical_slug
        HAVING COUNT(*) > 1
        ORDER BY canonical_slug
        """
    )
    for slug, identifiers, count in rows:
        _error(issues, "duplicate_canonical_slug", canonical_slug=slug, model_ids=identifiers, count=count)


def _append_overlapping_price_intervals(conn: sqlite3.Connection, issues: list[dict[str, Any]]) -> None:
    rows = conn.execute(
        """
        SELECT first.id, second.id, first.model_id, first.provider_surface_id, first.component,
               first.unit, first.currency, first.tier_condition_json, first.source_id, second.source_id
        FROM price_component AS first
        JOIN price_component AS second
          ON first.id < second.id
         AND first.model_id IS second.model_id
         AND first.provider_surface_id IS second.provider_surface_id
         AND first.component = second.component
         AND COALESCE(first.unit, '') = COALESCE(second.unit, '')
         AND COALESCE(first.currency, '') = COALESCE(second.currency, '')
         AND COALESCE(first.tier_condition_json, '') = COALESCE(second.tier_condition_json, '')
         AND (first.valid_to IS NULL OR second.valid_from IS NULL OR first.valid_to > second.valid_from)
         AND (second.valid_to IS NULL OR first.valid_from IS NULL OR second.valid_to > first.valid_from)
        ORDER BY first.id, second.id
        """
    )
    for first_id, second_id, model_id, surface_id, component, unit, currency, tier, first_source, second_source in rows:
        _error(
            issues,
            "overlapping_active_price_interval",
            first_price_component_id=first_id,
            second_price_component_id=second_id,
            model_id=model_id,
            provider_surface_id=surface_id,
            component=component,
            unit=unit,
            currency=currency,
            tier_condition_json=tier,
            source_ids=sorted((first_source, second_source), key=lambda value: value or ""),
        )


def _append_missing_snapshot_payloads(
    conn: sqlite3.Connection, issues: list[dict[str, Any]], raw_root: Path
) -> None:
    rows = conn.execute("SELECT id, raw_path FROM source_snapshot ORDER BY id")
    for snapshot_id, raw_path in rows:
        payload_path = raw_root / raw_path if raw_path else None
        if payload_path is None or not payload_path.is_file() or payload_path.stat().st_size == 0:
            _error(issues, "missing_snapshot_raw_payload", snapshot_id=snapshot_id, raw_path=raw_path)


def _append_missing_eval_conditions(conn: sqlite3.Connection, issues: list[dict[str, Any]]) -> None:
    rows = conn.execute(
        """
        SELECT id FROM benchmark_result
        WHERE TRIM(COALESCE(eval_condition_json, '')) = ''
        ORDER BY id
        """
    )
    for (result_id,) in rows:
        _warning(issues, "missing_benchmark_eval_condition", result_id=result_id)


def _result_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {"benchmark_results": int(conn.execute("SELECT COUNT(*) FROM benchmark_result").fetchone()[0])}


def _append_count_regressions(
    counts: dict[str, int], baseline_counts: dict[str, int], thresholds: dict[str, float], issues: list[dict[str, Any]]
) -> None:
    baseline = baseline_counts["benchmark_results"]
    current = counts["benchmark_results"]
    ratio = thresholds["max_benchmark_result_drop_ratio"]
    if not 0 <= ratio <= 1:
        raise ValueError("max_benchmark_result_drop_ratio must be between 0 and 1")
    if baseline and current < baseline * (1 - ratio):
        _error(
            issues,
            "catastrophic_benchmark_result_regression",
            current=current,
            baseline=baseline,
            max_drop_ratio=ratio,
        )


def _error(issues: list[dict[str, Any]], code: str, **details: Any) -> None:
    issues.append({"severity": "error", "code": code, "details": details})


def _warning(issues: list[dict[str, Any]], code: str, **details: Any) -> None:
    issues.append({"severity": "warning", "code": code, "details": details})


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check ModelDB SQLite data integrity before publishing exports.")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="target SQLite database (default: db/modeldb.sqlite)")
    parser.add_argument("--baseline", type=Path, help="optional prior SQLite export used for count-regression detection")
    parser.add_argument(
        "--max-benchmark-result-drop-ratio",
        type=float,
        default=DEFAULT_THRESHOLDS["max_benchmark_result_drop_ratio"],
        help="block when benchmark results drop by more than this fraction versus --baseline (default: 0.5)",
    )
    parser.add_argument("--raw-root", type=Path, default=REPO_ROOT, help="root used to resolve snapshot raw_path values")
    parser.add_argument(
        "--report-file",
        type=Path,
        help="write the complete machine-readable JSON report here and print only a compact JSON summary",
    )
    args = parser.parse_args(argv)
    report = run_checks(
        args.db,
        baseline_path=args.baseline,
        thresholds={"max_benchmark_result_drop_ratio": args.max_benchmark_result_drop_ratio},
        raw_root=args.raw_root,
    )
    if args.report_file is not None:
        args.report_file.parent.mkdir(parents=True, exist_ok=True)
        args.report_file.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        print(
            json.dumps(
                {
                    "blocked": report["blocked"],
                    "database": report["database"],
                    "report_file": str(args.report_file),
                    "summary": report["summary"],
                },
                sort_keys=True,
            )
        )
    else:
        print(json.dumps(report, sort_keys=True))
    print(
        f"data quality: {report['summary']['errors']} blocker(s), {report['summary']['warnings']} warning(s)",
        file=sys.stderr,
    )
    return 1 if report["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
