import json
import math
from typing import Any

from ingest.base import utcnow
from store.spine import link_model
from store.surfaces import surface_identity


_PRICE_COLUMNS = (
    "model_id, provider_surface_id, source_id, component, unit, currency, "
    "amount, normalized_usd_per_1m_tokens, tier_condition_json, valid_from, "
    "valid_to, source_snapshot_id"
)

_SOURCE_RECORD_SQL = """
    SELECT smr.source_snapshot_id, smr.source_model_id, smr.parsed_fields_json
    FROM source_model_record smr
    JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
    WHERE ss.source_id = ?
"""

_MODELS_DEV_COMPONENTS = (
    ("cost_input", "input_token"),
    ("cost_output", "output_token"),
    ("cost_cache_read", "cache_read"),
    ("cost_cache_write", "cache_write"),
)

_OPENROUTER_TOKEN_COMPONENTS = (
    ("price_prompt", "input_token"),
    ("price_completion", "output_token"),
)

_OPENROUTER_UNIT_COMPONENTS = (
    ("price_request", "request", "request"),
    ("price_image", "image", "image"),
)


def _parsed_fields(parsed_fields_json: str | None) -> dict[str, Any]:
    if not parsed_fields_json:
        return {}
    try:
        parsed = json.loads(parsed_fields_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_amount(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if math.isfinite(amount) else None


def _insert_price(
    conn,
    *,
    model_id: int,
    source_id: str,
    component: str,
    unit: str,
    amount: float,
    normalized: float | None,
    source_snapshot_id: int,
    valid_from: str,
    provider_surface_id: int | None = None,
) -> None:
    conn.execute(
        f"""
        INSERT INTO price_component ({_PRICE_COLUMNS})
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            model_id,
            provider_surface_id,
            source_id,
            component,
            unit,
            "USD",
            amount,
            normalized,
            None,
            valid_from,
            None,
            source_snapshot_id,
        ),
    )


def _models_dev_prices(parsed_fields: dict[str, Any]) -> list[tuple[str, str, float, float]]:
    prices: list[tuple[str, str, float, float]] = []
    for field, component in _MODELS_DEV_COMPONENTS:
        amount = _coerce_amount(parsed_fields.get(field))
        if amount is None:
            continue
        prices.append((component, "1m_tokens", amount, amount))
    return prices


def _openrouter_prices(parsed_fields: dict[str, Any]) -> list[tuple[str, str, float, float | None]]:
    prices: list[tuple[str, str, float, float | None]] = []
    for field, component in _OPENROUTER_TOKEN_COMPONENTS:
        amount = _coerce_amount(parsed_fields.get(field))
        if amount is None:
            continue
        prices.append((component, "token", amount, amount * 1_000_000))

    for field, component, unit in _OPENROUTER_UNIT_COMPONENTS:
        amount = _coerce_amount(parsed_fields.get(field))
        if amount is None:
            continue
        prices.append((component, unit, amount, None))
    return prices

def _canonical_developer(conn, model_id: int) -> str | None:
    row = conn.execute("SELECT developer_id FROM model WHERE id = ?", (model_id,)).fetchone()
    developer_id = row[0] if row else None
    return developer_id if isinstance(developer_id, str) and developer_id else None


def _lookup_surface_id(
    conn,
    *,
    source_id: str,
    source_model_id: str,
    parsed_fields: dict[str, Any],
    model_id: int,
) -> int | None:
    if source_id == "openrouter":
        candidates = [("openrouter", "openrouter", None, source_model_id)]
    else:
        provider_id, surface_type, region, endpoint_model_id = surface_identity(
            source_model_id=source_model_id,
            parsed_fields=parsed_fields,
            canonical_developer_id=_canonical_developer(conn, model_id),
        )
        candidates = [
            (provider_id, surface_type, region, endpoint_model_id),
        ]

    seen: set[tuple[str, str | None, str | None, str]] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        row = conn.execute(
            """
            SELECT id FROM provider_surface
            WHERE provider_id = ?
              AND surface_type IS ?
              AND region IS ?
              AND endpoint_model_id = ?
              AND model_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (*candidate, model_id),
        ).fetchone()
        if row:
            return int(row[0])
    return None


def _promote_source(conn, source_id: str, price_builder) -> tuple[int, int, int, set[int]]:
    inserted = 0
    unmatched = 0
    surface_linked = 0
    models_priced: set[int] = set()

    for source_snapshot_id, source_model_id, parsed_fields_json in conn.execute(
        _SOURCE_RECORD_SQL, (source_id,)
    ):
        parsed_fields = _parsed_fields(parsed_fields_json)
        prices = price_builder(parsed_fields)
        if not prices:
            continue

        model_id = link_model(
            conn,
            source_id=source_id,
            source_model_id=source_model_id,
            parsed_fields=parsed_fields,
        )
        if model_id is None:
            unmatched += 1
            continue

        provider_surface_id = _lookup_surface_id(
            conn,
            source_id=source_id,
            source_model_id=source_model_id,
            parsed_fields=parsed_fields,
            model_id=model_id,
        )
        valid_from = utcnow()
        for component, unit, amount, normalized in prices:
            _insert_price(
                conn,
                model_id=model_id,
                source_id=source_id,
                component=component,
                unit=unit,
                amount=amount,
                normalized=normalized,
                source_snapshot_id=source_snapshot_id,
                valid_from=valid_from,
                provider_surface_id=provider_surface_id,
            )
            inserted += 1
            if provider_surface_id is not None:
                surface_linked += 1
        models_priced.add(model_id)

    return inserted, unmatched, surface_linked, models_priced


def promote_prices(conn) -> dict[str, int]:
    conn.execute("DELETE FROM price_component WHERE source_id IN ('models_dev','openrouter')")

    inserted = 0
    unmatched = 0
    models_priced: set[int] = set()
    surface_linked = 0

    for source_id, price_builder in (
        ("models_dev", _models_dev_prices),
        ("openrouter", _openrouter_prices),
    ):
        (
            source_inserted,
            source_unmatched,
            source_surface_linked,
            source_models_priced,
        ) = _promote_source(conn, source_id, price_builder)
        inserted += source_inserted
        unmatched += source_unmatched
        surface_linked += source_surface_linked
        models_priced.update(source_models_priced)

    return {
        "inserted": inserted,
        "unmatched": unmatched,
        "models_priced": len(models_priced),
        "surface_linked": surface_linked,
    }


if __name__ == "__main__":
    from ingest.base import connect

    with connect() as c:
        print(promote_prices(c))
        c.commit()
