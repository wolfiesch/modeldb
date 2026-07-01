"""Entity-resolution layer for modeldb."""

from resolve.normalize import (
    ORG_SYNONYMS,
    canonical_org,
    extract_date_tokens,
    extract_modifiers,
    extract_surface_prefix,
    normalize_alias,
)
from resolve.resolver import (
    AUTO_MERGE_THRESHOLD,
    EXACT_PROVIDER_DOC,
    EXPLICIT_BRIDGE,
    NAME_ONLY,
    RELEASE_DATE_NAME_PRICE,
    SNAPSHOT_DATE_MATCH,
    enqueue_ambiguous,
    resolve_record,
    upsert_alias,
)

__all__ = [
    "AUTO_MERGE_THRESHOLD",
    "EXACT_PROVIDER_DOC",
    "EXPLICIT_BRIDGE",
    "NAME_ONLY",
    "ORG_SYNONYMS",
    "RELEASE_DATE_NAME_PRICE",
    "SNAPSHOT_DATE_MATCH",
    "canonical_org",
    "enqueue_ambiguous",
    "extract_date_tokens",
    "extract_modifiers",
    "extract_surface_prefix",
    "normalize_alias",
    "resolve_record",
    "upsert_alias",
]
