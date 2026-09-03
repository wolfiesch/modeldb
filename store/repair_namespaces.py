"""One-shot repair migration for multi-slash canonical slugs.

Historical ``build_spine`` runs minted provider-prefixed models.dev ids
verbatim as canonical rows whose ``developer_id`` names the HOST platform
instead of the creator::

    nvidia/meta/llama-3.1-70b-instruct      (developer should be meta)
    incepton-style: incepton/MiniMaxAI/MiniMax-M2.5
    poolside/poolside/laguna-m.1             (self-prefixed host path)
    thinkingmachines/thinkingmachines/Inkling-Small

That violates the locked ``{developer}/{family}-{variant}`` canonical format
(docs/PLAN.md) and fractures fact linkage: the same release accumulates facts
under both the creator-canonical row and the host shell. ``build_spine`` now
mints creator-canonical slugs (nested creator namespaces are stripped in
``spine.canonical_slug_for``); this module repairs the rows minted before
that fix.

Repair per shell row (``canonical_slug`` matching ``%/%/%``):

  1. derive the true developer + clean slug from the slug segments,
  2. find the canonical target — exact slug, normalized slug, then the
     ``link_model`` alias resolver — or create it carrying the shell's
     metadata (release dates, family, display name, ...),
  3. re-point every dependent FK row (MODEL_FK_REFERENCES below, enumerated
     from db/schema.sql),
  4. keep the host-facing slug string alive as a ``reexport_id`` alias of the
     canonical model,
  5. delete the shell row once nothing references it.

Merges are conservative: identical capability duplicates collapse, differing
capability conflicts SKIP the model (reported, never overwritten), and both
fact sets survive a merge. Idempotent: a second run plans nothing.

Usage::

    python3 -m store.repair_namespaces --dry-run
    python3 -m store.repair_namespaces --backup /path/to/backup.sqlite
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

from ingest.base import DB_PATH, utcnow
from resolve.normalize import canonical_org, normalize_alias
from store import spine

# Every column referencing model(id), enumerated from db/schema.sql. Extends
# spine.MODEL_FK_REFERENCES with entity_resolution_audit.candidate_model_id;
# kept local so spine's merge summaries stay byte-compatible with their tests.
MODEL_FK_REFERENCES = spine.MODEL_FK_REFERENCES + (
    ("entity_resolution_audit", "candidate_model_id"),
)

# Shell metadata carried onto a newly created canonical row.
_SHELL_COPY_COLUMNS = (
    "family", "generation", "tier_or_variant", "parameter_scale", "training_role",
    "release_date", "snapshot_date", "knowledge_cutoff", "stability",
    "open_weights", "display_name", "canonical_confidence",
)


class SkipRepair(RuntimeError):
    """A repair was refused conservatively; the shell row stays untouched."""


def _model_fk_counts(conn: sqlite3.Connection, model_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, column in MODEL_FK_REFERENCES:
        count = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",
            (model_id,),
        ).fetchone()[0]
        counts[f"{table}.{column}"] = int(count)
    return counts


def derive_clean_slug(canonical_slug: str) -> tuple[str, str] | None:
    """Derive ``(developer_id, clean_slug)`` from a host-prefixed slug.

    ``host/creator/model`` resolves to the creator's namespace;
    ``host/host/model`` (self-prefixed host path) resolves to the host's own
    namespace. Returns None for slugs without a nested segment.
    """
    host, creator, rest = canonical_slug.split("/", 2)
    if not rest:
        return None
    if canonical_org(creator) == canonical_org(host):
        developer = canonical_org(host)
    else:
        developer = canonical_org(creator)
    return developer, f"{developer}/{rest}"


def _normalized_slug_index(conn: sqlite3.Connection) -> dict[str, int]:
    """Map normalize_alias(canonical_slug) -> model_id for unambiguous slugs."""
    index: dict[str, int] = {}
    ambiguous: set[str] = set()
    for model_id, slug in conn.execute("SELECT id, canonical_slug FROM model"):
        normalized = normalize_alias(slug)
        if normalized in index:
            ambiguous.add(normalized)
            continue
        index[normalized] = int(model_id)
    for normalized in ambiguous:
        index.pop(normalized, None)
    return index


def _alias_resolved_target(
    conn: sqlite3.Connection,
    *,
    shell_model_id: int,
    creator_scoped_id: str,
    developer: str,
    rest: str,
) -> int | None:
    """Resolve a target via the spine alias matcher, guarded against mislinks.

    ``link_model`` is the same multi-pass resolver build_spine uses to attach
    re-export ids. Its bare-name pass can outrun the org hint, so a hit only
    counts when the matched model's slug model-part agrees with the nested
    ``rest`` segment (equal, or one is the other's hyphenated prefix) and,
    when the derived developer is a known organization, the developer matches.
    """
    candidate_model_id = spine.link_model(
        conn, source_id="models_dev", source_model_id=creator_scoped_id,
        parsed_fields={}, exclude_model_id=shell_model_id,
    )
    if candidate_model_id is None:
        return None
    row = conn.execute(
        "SELECT canonical_slug, developer_id FROM model WHERE id = ?",
        (candidate_model_id,),
    ).fetchone()
    target_slug, target_developer = str(row[0]), row[1]
    target_part = normalize_alias(target_slug.partition("/")[2] if "/" in target_slug else target_slug)
    norm_rest = normalize_alias(rest)
    slug_agrees = target_part in (norm_rest, norm_rest.rstrip("-")) or any(
        part.startswith(other + "-")
        for part, other in ((target_part, norm_rest), (norm_rest, target_part))
        if part and other
    )
    if not slug_agrees:
        return None
    org_known = conn.execute(
        "SELECT 1 FROM organization WHERE id = ?", (developer,)
    ).fetchone()
    if org_known and target_developer != developer:
        return None
    return int(candidate_model_id)


def _find_target_model(
    conn: sqlite3.Connection,
    *,
    norm_index: dict[str, int],
    shell_model_id: int,
    shell_slug: str,
    developer: str,
    clean_slug: str,
) -> tuple[int | None, str | None, str]:
    """Return (target_model_id, target_slug, resolution) for a repair plan."""
    row = conn.execute(
        "SELECT id FROM model WHERE canonical_slug = ?", (clean_slug,)
    ).fetchone()
    if row and int(row[0]) != shell_model_id:
        return int(row[0]), clean_slug, "exact"
    normalized_model_id = norm_index.get(normalize_alias(clean_slug))
    if normalized_model_id and normalized_model_id != shell_model_id:
        target_slug = conn.execute(
            "SELECT canonical_slug FROM model WHERE id = ?", (normalized_model_id,)
        ).fetchone()[0]
        return normalized_model_id, str(target_slug), "normalized"
    _host, creator, rest = shell_slug.split("/", 2)
    alias_model_id = _alias_resolved_target(
        conn, shell_model_id=shell_model_id, creator_scoped_id=f"{creator}/{rest}",
        developer=developer, rest=rest,
    )
    if alias_model_id is not None:
        target_slug = conn.execute(
            "SELECT canonical_slug FROM model WHERE id = ?", (alias_model_id,)
        ).fetchone()[0]
        return alias_model_id, str(target_slug), "alias"
    return None, None, "create"


def plan_namespace_repairs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Plan, but do not execute, canonical repairs for multi-slash slugs."""
    norm_index = _normalized_slug_index(conn)
    plans: list[dict[str, Any]] = []
    rows = conn.execute(
        """
        SELECT id, canonical_slug, developer_id FROM model
        WHERE canonical_slug LIKE '%/%/%'
        ORDER BY canonical_slug
        """
    ).fetchall()
    for model_id, canonical_slug, shell_developer_id in rows:
        derived = derive_clean_slug(canonical_slug)
        if derived is None:
            continue
        developer, clean_slug = derived
        target_model_id, target_slug, resolution = _find_target_model(
            conn, norm_index=norm_index, shell_model_id=int(model_id),
            shell_slug=canonical_slug, developer=developer, clean_slug=clean_slug,
        )
        plans.append(
            {
                "shell_model_id": int(model_id),
                "shell_slug": canonical_slug,
                "shell_developer_id": shell_developer_id,
                "developer_id": developer,
                "clean_slug": clean_slug,
                "target_model_id": target_model_id,
                "target_slug": target_slug,
                "target_resolution": resolution,
                "action": "merge" if target_model_id is not None else "create",
                "fk_counts": _model_fk_counts(conn, int(model_id)),
            }
        )
    return plans


def _collapse_identical_capability_conflicts(
    conn: sqlite3.Connection, plan: dict[str, Any]
) -> int:
    """Delete shell capability rows already present on the target (identical)."""
    deleted = 0
    for conflict in spine._model_capability_conflicts(
        conn, plan["shell_model_id"], plan["target_model_id"]
    ):
        differing = (
            conflict["duplicate_value"] != conflict["target_value"]
            or conflict["duplicate_confidence"] != conflict["target_confidence"]
        )
        if differing:
            raise SkipRepair(
                f"capability conflict for {conflict['capability']} "
                f"(snapshot {conflict['source_snapshot_id']}): shell="
                f"{conflict['duplicate_value']!r} target={conflict['target_value']!r}"
            )
        deleted += conn.execute(
            """
            DELETE FROM model_capability
            WHERE model_id = ? AND capability = ? AND source_snapshot_id = ?
            """,
            (
                plan["shell_model_id"],
                conflict["capability"],
                conflict["source_snapshot_id"],
            ),
        ).rowcount
    return deleted


def _ensure_host_alias(
    conn: sqlite3.Connection,
    *,
    shell_slug: str,
    shell_model_id: int,
    target_model_id: int,
    now: str,
) -> int:
    """Keep the host-facing slug string resolvable on the repaired canonical.

    Never steals an alias another canonical model owns; the re-pointed
    api_model_id alias usually already carries the string.
    """
    existing = conn.execute(
        """
        SELECT id, model_id FROM model_alias
        WHERE source_id = 'models_dev' AND alias_string = ?
          AND alias_kind = 'reexport_id' AND COALESCE(valid_from, '') = ''
        """,
        (shell_slug,),
    ).fetchone()
    if existing:
        if existing[1] in (None, shell_model_id, target_model_id):
            conn.execute(
                "UPDATE model_alias SET model_id = ?, last_seen_at = ? WHERE id = ?",
                (target_model_id, now, existing[0]),
            )
        return 0
    conn.execute(
        """
        INSERT INTO model_alias (
            source_id, alias_string, alias_normalized, alias_kind, model_id,
            resolution_method, confidence, first_seen_at, last_seen_at
        ) VALUES ('models_dev', ?, ?, 'reexport_id', ?, 'namespace_repair', 0.95, ?, ?)
        """,
        (shell_slug, normalize_alias(shell_slug), target_model_id, now, now),
    )
    return 1


def _create_canonical_from_shell(
    conn: sqlite3.Connection, plan: dict[str, Any], now: str
) -> int:
    """Create the creator-canonical model carrying the shell's metadata."""
    spine._ensure_org(conn, plan["developer_id"], plan["developer_id"])
    shell_row = conn.execute(
        f"SELECT {', '.join(_SHELL_COPY_COLUMNS)} FROM model WHERE id = ?",
        (plan["shell_model_id"],),
    ).fetchone()
    columns = ", ".join(_SHELL_COPY_COLUMNS)
    placeholders = ", ".join("?" * len(_SHELL_COPY_COLUMNS))
    cur = conn.execute(
        f"""
        INSERT INTO model (canonical_slug, developer_id, {columns}, created_at, updated_at)
        VALUES (?, ?, {placeholders}, ?, ?)
        """,
        (
            plan["clean_slug"], plan["developer_id"], *shell_row, now, now,
        ),
    )
    assert cur.lastrowid is not None  # sqlite3 sets lastrowid after a single-row INSERT
    return int(cur.lastrowid)

def _apply_one(
    conn: sqlite3.Connection, plan: dict[str, Any], summary: dict[str, Any], now: str
) -> None:
    shell_model_id = plan["shell_model_id"]
    target_model_id = plan["target_model_id"]
    if target_model_id is None:
        target_model_id = _create_canonical_from_shell(conn, plan, now)
        plan["target_model_id"] = target_model_id
        plan["target_slug"] = plan["clean_slug"]
        summary["created"] += 1
    else:
        summary["collapsed_capability_conflicts"] += (
            _collapse_identical_capability_conflicts(conn, plan)
        )
        summary["merged"] += 1

    summary["aliases_created"] += _ensure_host_alias(
        conn,
        shell_slug=plan["shell_slug"],
        shell_model_id=shell_model_id,
        target_model_id=target_model_id,
        now=now,
    )

    for table, column in MODEL_FK_REFERENCES:
        changed = conn.execute(
            f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
            (target_model_id, shell_model_id),
        ).rowcount
        key = f"{table}.{column}"
        summary["fk_counts"][key] = summary["fk_counts"].get(key, 0) + int(changed)

    remaining = {
        key: count
        for key, count in _model_fk_counts(conn, shell_model_id).items()
        if count
    }
    if remaining:
        raise SkipRepair(f"shell still referenced after re-point: {remaining}")

    deleted = conn.execute(
        "DELETE FROM model WHERE id = ?", (shell_model_id,)
    ).rowcount
    if deleted != 1:
        raise SkipRepair("expected to delete exactly one shell model row")
    summary["deleted_models"] += deleted
    summary["applied"] += 1


def apply_namespace_repairs(
    conn: sqlite3.Connection,
    *,
    backup_path: str | None = None,
    allow_test_memory_backup: bool = False,
) -> dict[str, Any]:
    """Apply namespace repair plans after concrete backup validation."""
    plans = plan_namespace_repairs(conn)
    summary: dict[str, Any] = {
        "planned": len(plans),
        "applied": 0,
        "created": 0,
        "merged": 0,
        "skipped_count": 0,
        "skipped_plans": [],
        "fk_counts": {},
        "aliases_created": 0,
        "deleted_models": 0,
        "collapsed_capability_conflicts": 0,
    }
    if not plans:
        return summary
    if not allow_test_memory_backup:
        if backup_path is None:
            raise RuntimeError(
                "Refusing to apply namespace repairs without a backup path; "
                'create one first: sqlite3 db/modeldb.sqlite ".backup /path/backup.sqlite"'
            )
        backup = Path(backup_path)
        if not backup.exists() or not backup.is_file() or backup.stat().st_size <= 0:
            raise RuntimeError(
                "Refusing to apply namespace repairs without an existing backup path."
            )

    now = utcnow()
    with conn:
        for plan in plans:
            conn.execute("SAVEPOINT repair_namespace")
            try:
                _apply_one(conn, plan, summary, now)
            except SkipRepair as skip:
                conn.execute("ROLLBACK TO repair_namespace")
                summary["skipped_count"] += 1
                summary["skipped_plans"].append(
                    {
                        "shell_model_id": plan["shell_model_id"],
                        "shell_slug": plan["shell_slug"],
                        "clean_slug": plan["clean_slug"],
                        "reason": str(skip),
                    }
                )
            finally:
                conn.execute("RELEASE repair_namespace")
    return summary


def _print_plans(plans: list[dict[str, Any]]) -> None:
    print(f"namespace repair plan: {len(plans)} shell rows (dry run)")
    for plan in plans:
        target = plan["target_slug"] or plan["clean_slug"]
        fk = " ".join(
            f"{key}={count}" for key, count in plan["fk_counts"].items() if count
        )
        resolution = plan["target_resolution"]
        print(
            f"  {plan['shell_slug']}  ->  {target}"
            f"  [{plan['action']} via {resolution}]  {fk}".rstrip()
        )
    actions = [plan["action"] for plan in plans]
    print(
        f"summary: {len(plans)} shells,"
        f" {actions.count('merge')} merges, {actions.count('create')} creates"
    )


def _print_summary(summary: dict[str, Any]) -> None:
    print(
        f"namespace repair applied: {summary['applied']}/{summary['planned']}"
        f" (created={summary['created']}, merged={summary['merged']},"
        f" skipped={summary['skipped_count']})"
    )
    for key, count in sorted(summary["fk_counts"].items()):
        if count:
            print(f"  {key}: {count}")
    if summary["aliases_created"]:
        print(f"  host aliases created: {summary['aliases_created']}")
    if summary["collapsed_capability_conflicts"]:
        print(
            "  identical capability conflicts collapsed:"
            f" {summary['collapsed_capability_conflicts']}"
        )
    for skipped in summary["skipped_plans"]:
        print(f"  SKIPPED {skipped['shell_slug']}: {skipped['reason']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m store.repair_namespaces",
        description="Collapse multi-slash canonical slugs onto creator-canonical models.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print the planned moves without writing",
    )
    parser.add_argument(
        "--db", default=str(DB_PATH),
        help="modeldb SQLite path (default: %(default)s)",
    )
    parser.add_argument(
        "--backup",
        help="existing backup file; required for a real (non-dry) run",
    )
    args = parser.parse_args(argv)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        if args.dry_run:
            _print_plans(plan_namespace_repairs(conn))
            return 0
        summary = apply_namespace_repairs(conn, backup_path=args.backup)
        _print_summary(summary)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
