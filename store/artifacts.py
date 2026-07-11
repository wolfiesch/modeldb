from __future__ import annotations

import json
import re
import sqlite3
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ingest.sources.huggingface import HuggingFaceParser

SOURCE_ID = "huggingface"
USER_AGENT = "modeldb-ingest/0.1"
HF_MODEL_API = "https://huggingface.co/api/models/{repo_id}"
HF_BULK_URL = "https://huggingface.co/api/models?known_ids=1"

# Anonymous Hub access is rate-limited. Keep enrichment bounded and source-driven:
# only known repo ids from resolved aliases or existing artifacts are fetched, capped
# well below the documented anonymous window instead of crawling /api/models.
HF_FETCH_LIMIT = 100

_QUANT_RE = re.compile(r"(?<![a-z0-9])q(?:[2-8])(?:_[a-z0-9]+)*(?![a-z0-9])")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _known_repo_ids(conn: sqlite3.Connection, limit: int = HF_FETCH_LIMIT) -> list[str]:
    seen: set[str] = set()
    repo_ids: list[str] = []

    def add(repo_id: Any) -> None:
        if len(repo_ids) >= limit or not isinstance(repo_id, str):
            return
        repo_id = repo_id.strip()
        if not repo_id or "/" not in repo_id or repo_id in seen:
            return
        seen.add(repo_id)
        repo_ids.append(repo_id)

    for (alias_string,) in conn.execute(
        """
        SELECT alias_string
        FROM model_alias
        WHERE alias_kind = 'hf_repo_id'
          AND model_id IS NOT NULL
        ORDER BY confidence DESC, last_seen_at DESC, alias_string
        """
    ):
        add(alias_string)

    for (artifact_ref,) in conn.execute(
        """
        SELECT artifact_ref
        FROM model_artifact
        WHERE artifact_type = 'hf_repo'
          AND model_id IS NOT NULL
        ORDER BY id
        """
    ):
        add(artifact_ref)

    return repo_ids


def _fetch_one(repo_id: str, timeout: float) -> dict[str, Any]:
    url = HF_MODEL_API.format(repo_id=quote(repo_id, safe="/"))
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {"repo_id": repo_id, "status": response.status, "body": body}
    except HTTPError as exc:
        raw = exc.read()
        try:
            body: Any = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {"error": raw.decode("utf-8", errors="replace")}
        return {"repo_id": repo_id, "status": exc.code, "body": body}
    except (TimeoutError, URLError, OSError) as exc:
        return {"repo_id": repo_id, "status": "error", "body": {"error": str(exc)}}


def fetch_huggingface_records(
    conn: sqlite3.Connection,
    *,
    limit: int = HF_FETCH_LIMIT,
    timeout: float = 30,
) -> dict[str, int]:
    """Fetch capped per-repo Hugging Face metadata for known ids and store records.

    This is intentionally not a Hub crawl. It reads only already-resolved
    hf_repo_id aliases plus existing HF artifact refs, caps the request count, and
    persists one JSON array payload compatible with HuggingFaceParser.parse().
    """

    safe_limit = max(0, min(int(limit), HF_FETCH_LIMIT))
    repo_ids = _known_repo_ids(conn, safe_limit)
    payload = [_fetch_one(repo_id, timeout) for repo_id in repo_ids]
    raw = _json_dumps(payload).encode("utf-8")

    parser = HuggingFaceParser()
    snapshot_id = parser.snapshot(conn, HF_BULK_URL, raw, {})
    records = parser.store_records(conn, snapshot_id, parser.parse(raw, snapshot_id))
    return {"repo_ids": len(repo_ids), "fetched": len(payload), "snapshot_id": snapshot_id, "records": records}


def _model_ids_by_repo(conn: sqlite3.Connection) -> dict[str, int]:
    model_ids: dict[str, int] = {}
    for repo_id, model_id in conn.execute(
        """
        SELECT alias_string, model_id
        FROM model_alias
        WHERE alias_kind = 'hf_repo_id'
          AND model_id IS NOT NULL
        ORDER BY confidence ASC, last_seen_at ASC
        """
    ):
        if isinstance(repo_id, str) and model_id is not None:
            model_ids[repo_id] = int(model_id)

    for repo_id, model_id in conn.execute(
        """
        SELECT artifact_ref, model_id
        FROM model_artifact
        WHERE artifact_type = 'hf_repo'
          AND model_id IS NOT NULL
        ORDER BY id ASC
        """
    ):
        if isinstance(repo_id, str) and model_id is not None:
            model_ids.setdefault(repo_id, int(model_id))

    return model_ids


def _hf_records(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for repo_id, parsed_json, raw_json in conn.execute(
        """
        SELECT smr.source_model_id, smr.parsed_fields_json, smr.raw_record_json
        FROM source_model_record smr
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE ss.source_id = 'huggingface'
        ORDER BY ss.fetched_at, smr.id
        """
    ):
        parsed = _json_loads(parsed_json)
        raw = _json_loads(raw_json)
        if isinstance(repo_id, str) and parsed:
            parsed["_raw_record"] = raw
            records[repo_id] = parsed
    return records


def _alias_repo_ids(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            """
            SELECT alias_string
            FROM model_alias
            WHERE alias_kind = 'hf_repo_id'
              AND model_id IS NOT NULL
            """
        )
        if row[0]
    }


def _metadata_for(parsed: dict[str, Any] | None, alias_only: bool) -> str:
    if not parsed:
        return _json_dumps({"source": "model_alias"}) if alias_only else "{}"

    metadata = {
        key: parsed.get(key)
        for key in (
            "repo_id",
            "modelId",
            "id",
            "tags",
            "pipeline_tag",
            "library_name",
            "cardData",
            "safetensors",
            "siblings",
            "downloads",
            "likes",
            "status",
        )
        if key in parsed
    }
    return _json_dumps(metadata)


def _upsert_artifact(
    conn: sqlite3.Connection,
    *,
    repo_id: str,
    model_id: int,
    parsed: dict[str, Any] | None,
    alias_only: bool,
) -> int:
    row = conn.execute(
        "SELECT id FROM model_artifact WHERE source_id = ? AND artifact_ref = ?",
        (SOURCE_ID, repo_id),
    ).fetchone()

    author = parsed.get("author") if parsed else None
    gated = parsed.get("gated") if parsed else None
    license_value = parsed.get("license") if parsed else None
    sha = parsed.get("sha") if parsed else None
    last_modified = parsed.get("lastModified") if parsed else None
    metadata_json = _metadata_for(parsed, alias_only)

    if row:
        conn.execute(
            """
            UPDATE model_artifact
            SET model_id = COALESCE(?, model_id),
                artifact_type = 'hf_repo',
                author = COALESCE(?, author),
                gated = COALESCE(?, gated),
                license = COALESCE(?, license),
                sha = COALESCE(?, sha),
                last_modified = COALESCE(?, last_modified),
                metadata_json = CASE WHEN ? != '{}' THEN ? ELSE metadata_json END
            WHERE id = ?
            """,
            (
                model_id,
                author,
                str(gated) if gated is not None else None,
                license_value,
                sha,
                last_modified,
                metadata_json,
                metadata_json,
                row[0],
            ),
        )
        return int(row[0])

    cur = conn.execute(
        """
        INSERT INTO model_artifact
          (model_id, source_id, artifact_ref, artifact_type, author, gated, license,
           sha, last_modified, metadata_json)
        VALUES (?, ?, ?, 'hf_repo', ?, ?, ?, ?, ?, ?)
        """,
        (
            model_id,
            SOURCE_ID,
            repo_id,
            author,
            str(gated) if gated is not None else None,
            license_value,
            sha,
            last_modified,
            metadata_json,
        ),
    )
    return int(cur.lastrowid)


def _format_from(name: str, tags: list[Any]) -> str | None:
    haystack = " ".join([name.lower(), *(str(tag).lower() for tag in tags)])
    if name.lower().endswith(".gguf") or "gguf" in haystack:
        return "gguf"
    if name.lower().endswith(".safetensors") or "safetensors" in haystack:
        return "safetensors"
    if "awq" in haystack:
        return "awq"
    if "fp8" in haystack:
        return "fp8"
    return None


def _quantization_from(name: str, tags: list[Any], fmt: str | None) -> str | None:
    name_text = name.lower()
    tags_text = " ".join(str(tag).lower() for tag in tags)
    normalized_name = name_text.replace("-", "_")
    normalized_tags = tags_text.replace("-", "_")

    if "awq" in name_text:
        return "awq"
    match = _QUANT_RE.search(normalized_name)
    if match:
        token = match.group(0)
        return f"gguf:{token}" if fmt == "gguf" else token
    if "fp8" in name_text or "f8" in name_text:
        return "fp8"
    if "awq" in tags_text:
        return "awq"
    if "fp8" in tags_text or "f8" in tags_text:
        return "fp8"
    match = _QUANT_RE.search(normalized_tags)
    if match:
        token = match.group(0)
        return f"gguf:{token}" if fmt == "gguf" else token
    return None


def _size_bytes(sibling: dict[str, Any]) -> int | None:
    for value in (
        sibling.get("size"),
        sibling.get("sizeBytes"),
        sibling.get("blob_size"),
        (sibling.get("lfs") or {}).get("size") if isinstance(sibling.get("lfs"), dict) else None,
    ):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _total_parameters(parsed: dict[str, Any]) -> int | None:
    safetensors = parsed.get("safetensors")
    if not isinstance(safetensors, dict):
        return None
    total = safetensors.get("total")
    try:
        return int(total) if total is not None else None
    except (TypeError, ValueError):
        return None


def _variant_rows(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    tags = parsed.get("tags") if isinstance(parsed.get("tags"), list) else []
    parameter_count = _total_parameters(parsed)
    variants: list[dict[str, Any]] = []

    siblings = parsed.get("siblings") if isinstance(parsed.get("siblings"), list) else []
    for sibling in siblings:
        if not isinstance(sibling, dict):
            continue
        name = sibling.get("rfilename") or sibling.get("filename") or sibling.get("name")
        if not isinstance(name, str) or not name:
            continue
        fmt = _format_from(name, tags)
        quantization = _quantization_from(name, tags, fmt)
        if fmt is None and quantization is None:
            continue
        size_bytes = _size_bytes(sibling)
        metadata = {"sizeBytes": size_bytes, "sibling": sibling}
        variants.append(
            {
                "quantization": quantization,
                "format": fmt,
                "parameter_count": parameter_count,
                "file_pattern": name,
                "metadata_json": _json_dumps(metadata),
            }
        )

    safetensors = parsed.get("safetensors")
    if isinstance(safetensors, dict) and parameter_count is not None and not any(v["format"] == "safetensors" for v in variants):
        variants.append(
            {
                "quantization": _quantization_from("", tags, "safetensors"),
                "format": "safetensors",
                "parameter_count": parameter_count,
                "file_pattern": "*.safetensors",
                "metadata_json": _json_dumps({"safetensors": safetensors}),
            }
        )

    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for variant in variants:
        key = (
            variant["quantization"],
            variant["format"],
            variant["parameter_count"],
            variant["file_pattern"],
        )
        unique.setdefault(key, variant)
    return list(unique.values())


def promote_artifacts(conn: sqlite3.Connection) -> dict[str, int]:
    model_ids = _model_ids_by_repo(conn)
    hf_records = _hf_records(conn)
    alias_repo_ids = _alias_repo_ids(conn)
    repo_ids = sorted(set(model_ids) | set(hf_records) | alias_repo_ids)

    artifacts_seen = 0
    artifacts_inserted = 0
    artifacts_updated = 0
    variants_inserted = 0
    unmatched = 0

    before = conn.execute(
        "SELECT COUNT(*) FROM model_artifact WHERE source_id = ?",
        (SOURCE_ID,),
    ).fetchone()[0]

    conn.execute(
        """
        DELETE FROM artifact_variant
        WHERE artifact_id IN (SELECT id FROM model_artifact WHERE source_id = 'huggingface')
        """
    )

    artifact_ids_by_repo: dict[str, int] = {}
    for repo_id in repo_ids:
        model_id = model_ids.get(repo_id)
        if model_id is None:
            unmatched += 1
            continue
        parsed = hf_records.get(repo_id)
        artifact_id = _upsert_artifact(
            conn,
            repo_id=repo_id,
            model_id=model_id,
            parsed=parsed,
            alias_only=repo_id in alias_repo_ids and parsed is None,
        )
        artifact_ids_by_repo[repo_id] = artifact_id
        artifacts_seen += 1

    after = conn.execute(
        "SELECT COUNT(*) FROM model_artifact WHERE source_id = ?",
        (SOURCE_ID,),
    ).fetchone()[0]
    artifacts_inserted = max(0, int(after) - int(before))
    artifacts_updated = max(0, artifacts_seen - artifacts_inserted)

    for repo_id, parsed in hf_records.items():
        artifact_id = artifact_ids_by_repo.get(repo_id)
        if artifact_id is None:
            continue
        for variant in _variant_rows(parsed):
            conn.execute(
                """
                INSERT INTO artifact_variant
                  (artifact_id, quantization, format, parameter_count, file_pattern, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    variant["quantization"],
                    variant["format"],
                    variant["parameter_count"],
                    variant["file_pattern"],
                    variant["metadata_json"],
                ),
            )
            variants_inserted += 1

    return {
        "artifacts_seen": artifacts_seen,
        "artifacts_inserted": artifacts_inserted,
        "artifacts_updated": artifacts_updated,
        "variants_inserted": variants_inserted,
        "unmatched": unmatched,
    }


if __name__ == "__main__":
    from ingest.base import connect

    with connect() as c:
        print(promote_artifacts(c))
        c.commit()
