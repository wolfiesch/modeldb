"""Spine-builder: promote models.dev first-party records into canonical `model`
rows + aliases, and expose the cross-source join helper `link_model()`.

Design notes (from live-payload recon):
  - models.dev top-level keys mix FIRST-PARTY vendors (anthropic, openai, xai, ...)
    with AGGREGATOR re-exporters (requesty, qiniu-ai, openrouter, ...). Only
    first-party providers are authoritative for canonical identity; aggregators
    would create duplicate `vendor/model` canonical rows. We build the spine from
    first-party providers, and let every other source attach as aliases/facts.
  - Each canonical model gets TWO normalized aliases: the full `provider/model`
    form AND the bare `model` form, so provider-less benchmark names (Epoch's
    `gpt-5.5`, `grok-4`) can still join.
  - link_model() is a multi-pass matcher used by the price + benchmark promoters.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from ingest.base import utcnow
from resolve.normalize import canonical_org, extract_modifiers, normalize_alias

# First-party model DEVELOPERS on models.dev — the only providers authoritative
# for canonical identity. Every other provider id (nano-gpt, openrouter, vercel,
# snowflake-cortex, wafer.ai, ...) re-exports these vendors' models and must NOT
# mint a canonical row; they attach as aliases/facts instead.
FIRST_PARTY_PROVIDERS = {
    "anthropic", "openai", "google", "xai", "meta", "llama", "mistral",
    "deepseek", "alibaba", "zhipuai", "zai", "moonshotai", "minimax",
    "cohere", "perplexity", "stepfun", "upstage", "xiaomi",
    "sarvam", "baidu", "tencent", "poolside", "sakana", "nova",
    "thinkingmachines", "meituan",
}

# models.dev also lists re-export namespaces that mirror other developers'
# models. They are useful source facts, but they must not mint canonical rows.
REEXPORT_ONLY_PROVIDERS = {"nvidia", "inceptron"}

# Some first-party developers ship through regional and subscription catalogs
# (`alibaba-cn`, `alibaba-token-plan`, `tencent-tokenhub`) instead of, or weeks
# before, their plain namespace. Those catalogs are the developer's own surface,
# but they also resell other vendors' models, so they mint canonical identity
# only for ids that belong to the developer itself (see `_mints_in_namespace`).
# Minting `alibaba-cn/qwen3.7-flash` verbatim would also create a second
# canonical row once `alibaba/qwen3.7-flash` appears, so the slug always carries
# the developer prefix.
MIXED_FIRST_PARTY_NAMESPACES = {
    "alibaba-cn": "alibaba",
    "alibaba-coding-plan": "alibaba",
    "alibaba-coding-plan-cn": "alibaba",
    "alibaba-token-plan": "alibaba",
    "alibaba-token-plan-cn": "alibaba",
    "tencent-coding-plan": "tencent",
    "tencent-token-plan": "tencent",
    "tencent-tokenhub": "tencent",
}

# Single-vendor product namespaces: the whole namespace is one developer's own
# catalog (`longcat` is Meituan's API), so every id in it mints.
PRODUCT_NAMESPACES = {"longcat": "meituan"}

_VERSION_SUFFIX_RE = re.compile(r"[\d.]+$")


def first_party_provider_id(provider_id: str) -> str:
    """Map a models.dev namespace onto the developer provider id that owns it."""
    if provider_id in MIXED_FIRST_PARTY_NAMESPACES:
        return MIXED_FIRST_PARTY_NAMESPACES[provider_id]
    return PRODUCT_NAMESPACES.get(provider_id, provider_id)


def canonical_slug_for(source_model_id: str) -> str:
    """Canonical slug for a first-party models.dev id, namespace-normalized."""
    provider_id, _, model_part = source_model_id.partition("/")
    nested_creator, nested_sep, nested_rest = model_part.partition("/")
    if nested_sep and is_first_party_provider(nested_creator):
        # Nested ids carry the creator namespace inside the model path
        # (`thinkingmachines/thinkingmachines/Inkling`,
        # `poolside/poolside/laguna-m.1`). Canonical identity is the
        # creator-canonical `creator/model` slug — never a 3-segment
        # host-prefixed one; the host string attaches as an alias instead.
        return f"{canonical_org(nested_creator)}/{nested_rest}"
    developer_provider = first_party_provider_id(provider_id)
    if not model_part or developer_provider == provider_id:
        return source_model_id
    return f"{developer_provider}/{model_part}"


def is_first_party_provider(provider_id: str) -> bool:
    """Return whether a models.dev provider id can mint canonical model rows."""
    provider = canonical_org(first_party_provider_id(provider_id))
    return provider in FIRST_PARTY_PROVIDERS and provider not in REEXPORT_ONLY_PROVIDERS


def _vendor_token(segment: str) -> str:
    """Identity token of a model-id segment: `qwen3.7` -> `qwen`, `2.0` -> ``."""
    return _VERSION_SUFFIX_RE.sub("", segment.split("-", 1)[0].lower())


def learn_vendor_tokens(source_model_ids: Iterable[str]) -> dict[str, set[str]]:
    """Map model-id tokens to the developers that ship them under their own name.

    Learned from the catalog itself rather than a hand-kept vendor list: every
    plain first-party namespace (`deepseek/deepseek-v4-flash`,
    `moonshotai/kimi-k2.5`, `zhipuai/glm-5`) teaches that `deepseek`, `kimi` and
    `glm` name those developers' models. A mixed catalog that lists the same
    token is reselling, not releasing.
    """
    tokens: dict[str, set[str]] = {}
    for source_model_id in source_model_ids:
        provider_id, _, bare = source_model_id.partition("/")
        if not bare or "/" in bare:
            continue
        if provider_id in MIXED_FIRST_PARTY_NAMESPACES or provider_id in PRODUCT_NAMESPACES:
            continue
        if not is_first_party_provider(provider_id):
            continue
        token = _vendor_token(bare)
        if token:
            tokens.setdefault(token, set()).add(canonical_org(provider_id))
    return tokens


def _mints_in_namespace(
    provider_id: str, bare_id: str, developer_id: str, vendor_tokens: dict[str, set[str]]
) -> bool:
    """Whether a mixed-catalog id is the catalog owner's own model.

    `alibaba-cn` lists Alibaba's `qwen3.7-flash` next to resold
    `deepseek-v4-flash`, `kimi-k2.5` and `siliconflow/deepseek-v3.2`. Only the
    first may mint an `alibaba/...` canonical row.
    """
    if provider_id not in MIXED_FIRST_PARTY_NAMESPACES:
        return True
    if "/" in bare_id:
        # Nested path (`siliconflow/deepseek-v3.2`) is always a resold listing.
        return False
    for segment in bare_id.split("-", 2)[:2]:
        owners = vendor_tokens.get(_vendor_token(segment))
        if owners and developer_id not in owners:
            return False
    return True


def find_alias_collisions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Report normalized aliases linked to more than one canonical model.

    This is intentionally read-only. Existing duplicate rows need an explicit
    backed-up FK migration step after the report has been reviewed.
    """
    aliases = conn.execute(
        """
        SELECT alias_normalized
        FROM model_alias
        WHERE model_id IS NOT NULL
        GROUP BY alias_normalized
        HAVING COUNT(DISTINCT model_id) > 1
        ORDER BY alias_normalized
        """
    ).fetchall()
    collisions: list[dict[str, Any]] = []
    for (alias_normalized,) in aliases:
        details = conn.execute(
            """
            SELECT DISTINCT ma.model_id, m.canonical_slug, ma.source_id,
                            ma.alias_string, ma.alias_kind, ma.confidence
            FROM model_alias ma
            JOIN model m ON m.id = ma.model_id
            WHERE ma.alias_normalized = ? AND ma.model_id IS NOT NULL
            ORDER BY m.canonical_slug, ma.model_id, ma.source_id, ma.alias_kind, ma.alias_string
            """,
            (alias_normalized,),
        ).fetchall()
        model_ids = sorted({int(row[0]) for row in details})
        canonical_slugs = sorted({str(row[1]) for row in details})
        collisions.append(
            {
                "alias_normalized": alias_normalized,
                "model_ids": model_ids,
                "canonical_slugs": canonical_slugs,
                "aliases": [
                    {
                        "model_id": int(model_id),
                        "canonical_slug": canonical_slug,
                        "source_id": source_id,
                        "alias_string": alias_string,
                        "alias_kind": alias_kind,
                        "confidence": confidence,
                    }
                    for model_id, canonical_slug, source_id, alias_string, alias_kind, confidence in details
                ],
            }
        )
    return collisions

MODEL_FK_REFERENCES = (
    ("model_alias", "model_id"),
    ("alias_history", "model_id"),
    ("entity_resolution_queue", "candidate_model_id"),
    ("provider_surface", "model_id"),
    ("model_artifact", "model_id"),
    ("model_capability", "model_id"),
    ("price_component", "model_id"),
    ("benchmark_result", "model_id"),
)


def plan_reexport_model_merges(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Plan, but do not execute, merges from re-export canonical rows to owners.

    The planner is intentionally conservative: it only proposes a merge when an
    alias collision contains one non-re-export target for a re-export duplicate.
    Actual FK rewrites and duplicate-row deletion belong in a separate backed-up
    migration step.
    """
    plans: list[dict[str, Any]] = []
    seen_duplicates: set[int] = set()
    for collision in find_alias_collisions(conn):
        models = {
            int(alias["model_id"]): str(alias["canonical_slug"])
            for alias in collision["aliases"]
        }
        targets = [
            (model_id, slug)
            for model_id, slug in models.items()
            if _reexport_provider(slug) is None
        ]
        duplicates = [
            (model_id, slug, provider)
            for model_id, slug in models.items()
            for provider in [_reexport_provider(slug)]
            if provider is not None
        ]
        if len(targets) != 1:
            continue
        target_model_id, target_slug = targets[0]
        for duplicate_model_id, duplicate_slug, provider in duplicates:
            if duplicate_model_id in seen_duplicates:
                continue
            seen_duplicates.add(duplicate_model_id)
            plans.append(
                {
                    "duplicate_model_id": duplicate_model_id,
                    "duplicate_slug": duplicate_slug,
                    "target_model_id": target_model_id,
                    "target_slug": target_slug,
                    "reexport_provider": provider,
                    "fk_counts": _model_fk_counts(conn, duplicate_model_id),
                    "capability_conflicts": _model_capability_conflicts(
                        conn, duplicate_model_id, target_model_id
                    ),
                }
            )
    return plans


def apply_reexport_model_merges(
    conn: sqlite3.Connection,
    *,
    backup_path: str | None = None,
    allow_test_memory_backup: bool = False,
    allow_identical_capability_conflicts: bool = False,
    skip_differing_capability_conflicts: bool = False,
) -> dict[str, Any]:
    """Apply re-export duplicate merge plans after concrete backup validation."""
    plans = plan_reexport_model_merges(conn)
    summary: dict[str, Any] = {
        "applied_count": 0,
        "skipped_count": 0,
        "skipped_plans": [],
        "fk_counts": {},
        "deleted_models": 0,
        "collapsed_capability_conflicts": 0,
    }
    if not plans:
        return summary
    if not allow_test_memory_backup:
        if backup_path is None:
            raise RuntimeError("Refusing to apply re-export model merges without a backup path.")
        backup = Path(backup_path)
        if not backup.exists() or not backup.is_file() or backup.stat().st_size <= 0:
            raise RuntimeError("Refusing to apply re-export model merges without an existing backup path.")

    safe_plans: list[dict[str, Any]] = []
    for plan in plans:
        conflicts = plan["capability_conflicts"]
        differing = [
            conflict for conflict in conflicts
            if (
                conflict["duplicate_value"] != conflict["target_value"]
                or conflict["duplicate_confidence"] != conflict["target_confidence"]
            )
        ]
        if differing:
            if not skip_differing_capability_conflicts:
                raise RuntimeError("Refusing to merge differing model capability confidence or values.")
            skipped = {
                "duplicate_model_id": plan["duplicate_model_id"],
                "duplicate_slug": plan["duplicate_slug"],
                "target_model_id": plan["target_model_id"],
                "target_slug": plan["target_slug"],
                "reexport_provider": plan["reexport_provider"],
                "capability_conflicts": differing,
            }
            summary["skipped_plans"].append(skipped)
            summary["skipped_count"] += 1
            continue
        if conflicts and not allow_identical_capability_conflicts:
            raise RuntimeError("Refusing to merge model capability conflicts without explicit allowance.")
        safe_plans.append(plan)

    if not safe_plans:
        return summary

    with conn:
        for plan in safe_plans:
            duplicate_model_id = int(plan["duplicate_model_id"])
            target_model_id = int(plan["target_model_id"])

            for conflict in plan["capability_conflicts"]:
                deleted = conn.execute(
                    """
                    DELETE FROM model_capability
                    WHERE model_id = ?
                      AND capability = ?
                      AND source_snapshot_id = ?
                    """,
                    (
                        duplicate_model_id,
                        conflict["capability"],
                        conflict["source_snapshot_id"],
                    ),
                ).rowcount
                summary["collapsed_capability_conflicts"] += deleted

            for table, column in MODEL_FK_REFERENCES:
                changed = conn.execute(
                    f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
                    (target_model_id, duplicate_model_id),
                ).rowcount
                key = f"{table}.{column}"
                planned = int(plan["fk_counts"].get(key, changed))
                summary["fk_counts"][key] = summary["fk_counts"].get(key, 0) + planned

            remaining = {
                key: count
                for key, count in _model_fk_counts(conn, duplicate_model_id).items()
                if count
            }
            if remaining:
                raise RuntimeError(f"Refusing to delete model with remaining references: {remaining}")

            deleted_model = conn.execute(
                "DELETE FROM model WHERE id = ?",
                (duplicate_model_id,),
            ).rowcount
            if deleted_model != 1:
                raise RuntimeError("Expected to delete exactly one duplicate model row.")
            summary["deleted_models"] += deleted_model
            summary["applied_count"] += 1

    return summary


def _reexport_provider(canonical_slug: str) -> str | None:
    if "/" not in canonical_slug:
        return None
    provider = canonical_slug.split("/", 1)[0]
    return provider if provider in REEXPORT_ONLY_PROVIDERS else None


def _model_fk_counts(conn: sqlite3.Connection, model_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, column in MODEL_FK_REFERENCES:
        count = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",
            (model_id,),
        ).fetchone()[0]
        counts[f"{table}.{column}"] = int(count)
    return counts


def _model_capability_conflicts(
    conn: sqlite3.Connection,
    duplicate_model_id: int,
    target_model_id: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT dup.capability, dup.source_snapshot_id,
               dup.value AS duplicate_value, target.value AS target_value,
               dup.confidence AS duplicate_confidence,
               target.confidence AS target_confidence
        FROM model_capability dup
        JOIN model_capability target
          ON target.model_id = ?
         AND target.capability = dup.capability
         AND target.source_snapshot_id = dup.source_snapshot_id
        WHERE dup.model_id = ?
        ORDER BY dup.capability, dup.source_snapshot_id
        """,
        (target_model_id, duplicate_model_id),
    ).fetchall()
    return [
        {
            "duplicate_model_id": duplicate_model_id,
            "target_model_id": target_model_id,
            "capability": capability,
            "source_snapshot_id": source_snapshot_id,
            "duplicate_value": duplicate_value,
            "target_value": target_value,
            "duplicate_confidence": duplicate_confidence,
            "target_confidence": target_confidence,
        }
        for (
            capability,
            source_snapshot_id,
            duplicate_value,
            target_value,
            duplicate_confidence,
            target_confidence,
        ) in rows
    ]


def _norm_variants(source_model_id: str) -> list[str]:
    """Normalized alias forms for a `provider/model` id: full + bare model."""
    variants = [normalize_alias(source_model_id)]
    if "/" in source_model_id:
        variants.append(normalize_alias(source_model_id.split("/", 1)[1]))
    # de-dupe, preserve order
    seen: dict[str, None] = {}
    for v in variants:
        if v:
            seen.setdefault(v, None)
    return list(seen)

def _provider_scoped_norm_variants(source_model_id: str) -> list[str]:
    """Normalized alias forms for sources where bare names are collision-prone."""
    normalized = normalize_alias(source_model_id)
    return [normalized] if normalized else []


def _artificial_analysis_candidates(parsed_fields: dict[str, Any]) -> list[str]:
    """Provider-scoped AA aliases derived from creator slug plus model slug/name."""
    creator = parsed_fields.get("model_creator_slug")
    if not isinstance(creator, str) or not creator.strip():
        return []

    raw_candidates: list[str] = []
    for identity in (parsed_fields.get("slug"), parsed_fields.get("name"), parsed_fields.get("model_name")):
        if not isinstance(identity, str) or not identity.strip():
            continue
        normalized_identity = normalize_alias(identity)
        for variant in _aa_identity_variants(normalized_identity):
            raw_candidates.append(f"{creator}/{variant}")

    seen: dict[str, None] = {}
    for candidate in raw_candidates:
        for normalized in _provider_scoped_norm_variants(candidate):
            seen.setdefault(normalized, None)
    return list(seen)


def _aa_identity_variants(identity: str) -> list[str]:
    """AA display names use marketing order and reasoning suffixes."""
    variants = [identity]
    match = re.match(r"^(claude)-(\d(?:-\d)?)-(opus|sonnet|haiku)(.*)$", identity)
    if match:
        variants.append(f"{match.group(1)}-{match.group(3)}-{match.group(2)}{match.group(4)}")

    base = identity
    suffixes = (
        "-non-reasoning-low-effort",
        "-non-reasoning-high-effort",
        "-adaptive-reasoning-max-effort",
        "-non-reasoning",
        "-reasoning",
        "-thinking",
        "-adaptive",
        "-high",
        "-medium",
        "-low",
        "-xhigh",
    )
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                variants.append(base)
                changed = True
                break

    seen: dict[str, None] = {}
    for variant in variants:
        if variant:
            seen.setdefault(variant, None)
    return list(seen)


def build_spine(conn: sqlite3.Connection) -> dict[str, int]:
    """Create canonical `model` rows + aliases from models.dev first-party records.

    Only the newest models.dev snapshot mints identity: the catalog renames ids
    (`thinkingmachines/inkling` -> `thinkingmachines/thinkingmachines/Inkling`),
    and replaying every historical snapshot would mint one canonical row per
    spelling. Rows minted by earlier runs are never removed here.

    Idempotent on canonical_slug and (source_id, alias_string). Returns a summary.
    """
    now = utcnow()
    rows = conn.execute(
        """
        SELECT smr.source_model_id, smr.display_name, smr.parsed_fields_json
        FROM source_model_record smr
        WHERE smr.source_snapshot_id = (
            SELECT MAX(id) FROM source_snapshot WHERE source_id = 'models_dev'
        )
        """
    ).fetchall()

    vendor_tokens = learn_vendor_tokens(row[0] for row in rows)
    models_created = 0
    aliases_created = 0
    variant_specs: list[tuple[str, str]] = []
    resold_specs: list[str] = []
    for source_model_id, display_name, parsed_json in rows:
        provider_id = source_model_id.split("/", 1)[0]
        if not is_first_party_provider(provider_id):
            continue
        if ":" in source_model_id:
            # `<id>:peft:262144`-style suffixes are serving variants, not distinct
            # releases. Attach them as aliases once every base row exists.
            variant_specs.append(
                (source_model_id, canonical_slug_for(source_model_id.split(":", 1)[0]))
            )
            continue

        bare_id = source_model_id.partition("/")[2]
        if bare_id and not _mints_in_namespace(
            provider_id, bare_id, canonical_org(first_party_provider_id(provider_id)),
            vendor_tokens,
        ):
            # A mixed catalog reselling another vendor: keep it as an alias fact.
            resold_specs.append(source_model_id)
            continue
        pf: dict[str, Any] = json.loads(parsed_json) if parsed_json else {}

        canonical_slug = canonical_slug_for(source_model_id)

        if canonical_slug.count("/") > 1:
            # Nested namespace we cannot attribute to a first-party creator
            # (`host/other-org/model`): minting verbatim would break the locked
            # `{developer}/{family}-{variant}` slug format. Keep the record as
            # an alias fact via the re-export path below.
            resold_specs.append(source_model_id)
            continue
        # The leading canonical_slug segment is always the creator: nested ids
        # are creator-stripped in canonical_slug_for, and namespace-mapped
        # slugs (`alibaba-cn/...` -> `alibaba/...`) carry the developer.
        developer_provider = canonical_slug.partition("/")[0]
        developer_id = canonical_org(developer_provider)
        release_date = pf.get("release_date")
        snapshot_date = release_date  # models.dev release_date is the dated snapshot

        cur = conn.execute("SELECT id FROM model WHERE canonical_slug = ?", (canonical_slug,))
        existing = cur.fetchone()
        if existing:
            model_id = existing[0]
        else:
            _ensure_org(conn, developer_id, developer_provider)
            cur = conn.execute(
                """
                INSERT INTO model (canonical_slug, developer_id, family, tier_or_variant,
                                   release_date, snapshot_date, knowledge_cutoff,
                                   open_weights, canonical_confidence, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (canonical_slug, developer_id, pf.get("family"), pf.get("model_id"),
                 release_date, snapshot_date, pf.get("knowledge"),
                 1 if pf.get("open_weights") else 0 if pf.get("open_weights") is not None else None,
                 "verified", now, now),
            )
            model_id = cur.lastrowid
            models_created += 1

        # Distinct alias rows so both forms persist under the unique index:
        #   full `provider/model` (api_model_id) AND bare `model` (bare_name).
        # link_model matches on alias_normalized regardless of kind.
        alias_specs = [(source_model_id, "api_model_id")]
        if "/" in source_model_id:
            bare = source_model_id.split("/", 1)[1]
            alias_specs.append((bare, "bare_name"))
        for alias_str, kind in alias_specs:
            aliases_created += _write_alias(
                conn, source_id="models_dev", alias_string=alias_str,
                alias_normalized=normalize_alias(alias_str), alias_kind=kind,
                model_id=model_id, method="exact_provider_doc", confidence=1.0, now=now,
            )

    for alias_str, base_slug in variant_specs:
        base = conn.execute("SELECT id FROM model WHERE canonical_slug = ?", (base_slug,)).fetchone()
        if base is None:
            continue
        aliases_created += _write_alias(
            conn, source_id="models_dev", alias_string=alias_str,
            alias_normalized=normalize_alias(alias_str), alias_kind="variant_id",
            model_id=base[0], method="variant_suffix_of_canonical", confidence=0.9, now=now,
        )

    resold = set(resold_specs)
    reexport_aliases_created = 0
    for source_model_id, _display_name, parsed_json in rows:
        provider_id = source_model_id.split("/", 1)[0]
        if "/" not in source_model_id:
            continue
        if provider_id not in REEXPORT_ONLY_PROVIDERS and source_model_id not in resold:
            continue
        pf: dict[str, Any] = json.loads(parsed_json) if parsed_json else {}
        target_model_id = source_model_id.split("/", 1)[1]
        model_id = link_model(
            conn,
            source_id="models_dev",
            source_model_id=target_model_id,
            parsed_fields=pf,
        )
        if model_id is None:
            continue
        created = _write_alias(
            conn, source_id="models_dev", alias_string=source_model_id,
            alias_normalized=normalize_alias(source_model_id), alias_kind="reexport_id",
            model_id=model_id, method="reexport_normalized_match", confidence=0.85, now=now,
        )
        reexport_aliases_created += created
        aliases_created += created
    conn.commit()
    return {
        "models_created": models_created,
        "aliases_created": aliases_created,
        "reexport_aliases_created": reexport_aliases_created,
    }


def bridge_openrouter_aliases(conn: sqlite3.Connection) -> dict[str, int]:
    """Attach OpenRouter ids + hugging_face_ids as aliases onto spine models.

    Matches OpenRouter `id` (provider/model) to canonical models by normalized
    form; when matched, also records the hugging_face_id as an hf_repo_id alias so
    the resolver's HF bridge can later link open-weight artifacts.
    """
    now = utcnow()
    rows = conn.execute(
        """
        SELECT smr.source_model_id, smr.parsed_fields_json
        FROM source_model_record smr
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE ss.source_id = 'openrouter'
        """
    ).fetchall()
    linked = 0
    hf = 0
    for source_model_id, parsed_json in rows:
        pf = json.loads(parsed_json) if parsed_json else {}
        model_id = link_model(conn, source_id="openrouter",
                              source_model_id=source_model_id, parsed_fields=pf)
        if model_id is None:
            continue
        linked += _write_alias(
            conn, source_id="openrouter", alias_string=source_model_id,
            alias_normalized=normalize_alias(source_model_id), alias_kind="router_id",
            model_id=model_id, method="normalized_match", confidence=0.9, now=now,
        )
        hf_id = pf.get("hugging_face_id")
        if hf_id:
            hf += _write_alias(
                conn, source_id="openrouter", alias_string=hf_id,
                alias_normalized=normalize_alias(hf_id), alias_kind="hf_repo_id",
                model_id=model_id, method="hf_id_bridge", confidence=0.95, now=now,
            )
    conn.commit()
    return {"openrouter_linked": linked, "hf_aliases": hf}


def _suffix_reductions(identity: str) -> list[str]:
    """Progressively strip trailing serving/effort modifiers from a source model
    name so it can match a canonical slug. Cross-source (Epoch + LMArena).

    Iteratively peels (either `_`- or `-`-separated), most-specific first:
      thinking[-NNk] · effort (max/xhigh/high/medium/low/min) · token budget (NNk)
      · latest · preview · trailing -YYYY-MM-DD or -MM-DD date.
    Also strips a leading `chatgpt-` marketing prefix. Returns each reduced form.
    """
    import re

    out: list[str] = []
    base = identity
    # marketing prefix: chatgpt-4o-latest -> gpt-4o-latest (canonical uses gpt-)
    if base.lower().startswith("chatgpt-"):
        base = "gpt-" + base[len("chatgpt-"):]
        out.append(base)

    tail = re.compile(
        r"^(.*?)[-_](?:"
        r"thinking(?:[-_]\d+k)?|"
        r"max|xhigh|high|medium|low|min|"
        r"\d+k|latest|preview|exp|beta"
        r")$",
        re.IGNORECASE,
    )
    date = re.compile(r"^(.*?)[-_]\d{4}-\d{2}-\d{2}$")
    short_date = re.compile(r"^(.*?)-\d{2}-\d{2}$")

    # iterate so stacked suffixes peel: ...-20251101-thinking-32k -> ... -> base
    changed = True
    while changed:
        changed = False
        for rx in (tail, date, short_date):
            m = rx.match(base)
            if m and m.group(1) and m.group(1) != base:
                base = m.group(1)
                out.append(base)
                changed = True
                break
    return out


def link_model(conn: sqlite3.Connection, *, source_id: str,
               source_model_id: str, parsed_fields: dict[str, Any],
               exclude_model_id: int | None = None) -> int | None:
    """Return the canonical model_id for a source record, or None.

    Multi-pass, most-confident first:
      1. exact alias_string already resolved
      2. normalized full form (provider/model)
      3. normalized bare model form (strip provider)
      4. Epoch-style: strip effort/quant modifiers (`_max`,`-high`,`fp8`) then bare match

    ``exclude_model_id`` skips a model's own aliases (used by the namespace
    repair so a multi-slash shell does not resolve onto itself).
    """
    # 1. exact alias hit. Artificial Analysis rows are third-party UUIDs or
    # provider-scoped names, so they must not resolve through bare display aliases
    # before the provider-scoped candidate path below.
    if source_id != "artificialanalysis":
        row = conn.execute(
            "SELECT model_id FROM model_alias WHERE alias_string = ? AND model_id IS NOT NULL "
            "AND (model_id IS NOT ?) "
            "ORDER BY confidence DESC LIMIT 1", (source_model_id, exclude_model_id)).fetchone()
        if row:
            return int(row[0])

    # For epoch, the joinable identity lives in parsed_fields['model_version'].
    identity = parsed_fields.get("model_version") or source_model_id

    if source_id == "artificialanalysis":
        candidates = _artificial_analysis_candidates(parsed_fields)
    else:
        candidates = list(_norm_variants(identity))
        # Epoch identities carry trailing effort/token/date suffixes that canonical
        # slugs lack: `gpt-5-2025-08-07_high`, `claude-opus-4-6_64K`, `..._max`.
        # Progressively strip and add each reduced form as a candidate.
        for reduced in _suffix_reductions(identity):
            candidates.extend(_norm_variants(reduced))
        # generic modifier strip (fp8/quant/etc.)
        stripped = identity
        for mod in extract_modifiers(identity):
            stripped = stripped.replace(mod, "")
        stripped = stripped.strip(" -_/")
        if stripped and stripped != identity:
            candidates.extend(_norm_variants(stripped))

    # Derive an org hint to disambiguate a bare name shared across developers.
    org_hint = _org_hint(source_id, source_model_id, parsed_fields)
    for cand in candidates:
        if not cand:
            continue
        matches = conn.execute(
            "SELECT ma.model_id, m.developer_id FROM model_alias ma "
            "JOIN model m ON m.id = ma.model_id "
            "WHERE ma.alias_normalized = ? AND ma.model_id IS NOT NULL "
            "ORDER BY ma.confidence DESC", (cand,)).fetchall()
        if exclude_model_id is not None:
            matches = [match for match in matches if match[0] != exclude_model_id]
        if not matches:
            continue
        if org_hint:
            for model_id, dev in matches:
                if dev and dev == org_hint:
                    return int(model_id)
        return int(matches[0][0])
    return None


def _org_hint(source_id: str, source_model_id: str,
              parsed_fields: dict[str, Any]) -> str | None:
    """Best-effort canonical developer id from source-specific provenance."""
    raw = None
    if source_id == "epoch":
        raw = parsed_fields.get("organization")
    elif source_id == "openrouter":
        # OpenRouter id is `vendor/model`; vendor is the developer.
        raw = source_model_id.split("/", 1)[0] if "/" in source_model_id else None
        hf = parsed_fields.get("hugging_face_id")
        if not raw and hf and "/" in hf:
            raw = hf.split("/", 1)[0]
    elif source_id == "frontierswe":
        raw = parsed_fields.get("provider_name") or parsed_fields.get("developer_id")
    elif "/" in source_model_id:
        raw = source_model_id.split("/", 1)[0]
    return canonical_org(raw) if raw else None


def _write_alias(conn, *, source_id, alias_string, alias_normalized, alias_kind,
                 model_id, method, confidence, now) -> int:
    """Idempotent alias upsert against the unique index. Returns 1 if inserted."""
    existing = conn.execute(
        "SELECT id FROM model_alias WHERE source_id=? AND alias_string=? AND alias_kind=? "
        "AND COALESCE(valid_from,'')=''", (source_id, alias_string, alias_kind)).fetchone()
    if existing:
        conn.execute("UPDATE model_alias SET model_id=?, last_seen_at=? WHERE id=?",
                     (model_id, now, existing[0]))
        return 0
    conn.execute(
        """INSERT INTO model_alias (source_id, alias_string, alias_normalized, alias_kind,
             model_id, resolution_method, confidence, first_seen_at, last_seen_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (source_id, alias_string, alias_normalized, alias_kind, model_id, method,
         confidence, now, now))
    return 1


def _ensure_org(conn, org_id: str | None, fallback_name: str) -> None:
    if not org_id:
        return
    conn.execute(
        "INSERT OR IGNORE INTO organization (id, display_name) VALUES (?,?)",
        (org_id, fallback_name))


if __name__ == "__main__":
    from ingest.base import connect
    with connect() as c:
        print(build_spine(c))
        print(bridge_openrouter_aliases(c))
