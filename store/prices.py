import json
import math
from typing import Any

from ingest.base import utcnow
from store.spine import link_model


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
) -> None:
    conn.execute(
        f"""
        INSERT INTO price_component ({_PRICE_COLUMNS})
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            model_id,
            None,
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


def _promote_source(conn, source_id: str, price_builder) -> tuple[int, int, set[int]]:
    inserted = 0
    unmatched = 0
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
            )
            inserted += 1
        models_priced.add(model_id)

    return inserted, unmatched, models_priced


def promote_prices(conn) -> dict[str, int]:
    conn.execute("DELETE FROM price_component WHERE source_id IN ('models_dev','openrouter')")

    inserted = 0
    unmatched = 0
    models_priced: set[int] = set()

    for source_id, price_builder in (
        ("models_dev", _models_dev_prices),
        ("openrouter", _openrouter_prices),
    ):
        source_inserted, source_unmatched, source_models_priced = _promote_source(
            conn, source_id, price_builder
        )
        inserted += source_inserted
        unmatched += source_unmatched
        models_priced.update(source_models_priced)

    return {
        "inserted": inserted,
        "unmatched": unmatched,
        "models_priced": len(models_priced),
    }


if __name__ == "__main__":
    from ingest.base import connect

    with connect() as c:
        print(promote_prices(c))
        c.commit()
