from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

_CAPABILITY_COLUMNS = "model_id, capability, value, source_snapshot_id, confidence"

_CLEAR_NAME_ARCHES = (
    (re.compile(r"\bqwen[-_ ]?3[-_ ]?moe\b", re.I), "Qwen3MoeForCausalLM"),
    (re.compile(r"\bqwen[-_ ]?3\b", re.I), "Qwen3ForCausalLM"),
    (re.compile(r"\bqwen[-_ ]?2[-_ ]?moe\b", re.I), "Qwen2MoeForCausalLM"),
    (re.compile(r"\bqwen[-_ ]?2[-_ ]?vl\b", re.I), "Qwen2VLForConditionalGeneration"),
    (re.compile(r"\bqwen[-_ ]?2\b", re.I), "Qwen2ForCausalLM"),
    (re.compile(r"\bllama[-_ ]?4\b", re.I), "Llama4ForCausalLM"),
    (re.compile(r"\bllama\b", re.I), "LlamaForCausalLM"),
    (re.compile(r"\bmixtral\b", re.I), "MixtralForCausalLM"),
    (re.compile(r"\bmistral\b", re.I), "MistralForCausalLM"),
    (re.compile(r"\bgemma[-_ ]?3\b", re.I), "Gemma3ForCausalLM"),
    (re.compile(r"\bgemma[-_ ]?2\b", re.I), "Gemma2ForCausalLM"),
    (re.compile(r"\bgemma\b", re.I), "GemmaForCausalLM"),
    (re.compile(r"\bphi[-_ ]?3\b", re.I), "Phi3ForCausalLM"),
    (re.compile(r"\bphi\b", re.I), "PhiForCausalLM"),
)


def promote_vllm(conn: sqlite3.Connection) -> dict[str, int]:
    """Promote HF artifact metadata into vLLM compatibility capabilities."""

    conn.execute(
        """
        DELETE FROM model_capability
        WHERE source_snapshot_id IN (
            SELECT id FROM source_snapshot WHERE source_id = 'vllm'
        )
        """
    )

    registry = _vllm_registry(conn)
    if not registry:
        return {"artifacts_seen": 0, "matched": 0, "capabilities_inserted": 0, "skipped": 0}

    artifacts_seen = 0
    matched = 0
    capabilities_inserted = 0
    skipped = 0

    for model_id, artifact_ref, metadata_json in _hf_artifacts(conn):
        artifacts_seen += 1
        metadata = _json_object(metadata_json)
        match = _match_architecture(metadata, artifact_ref, registry)
        if match is None:
            skipped += 1
            continue

        architecture, confidence = match
        record = registry[architecture]
        source_snapshot_id = int(record["source_snapshot_id"])
        backend = str(record.get("backend") or "native")

        _insert_capability(
            conn,
            model_id=model_id,
            capability="vllm_supported",
            value="true",
            source_snapshot_id=source_snapshot_id,
            confidence=confidence,
        )
        _insert_capability(
            conn,
            model_id=model_id,
            capability="vllm_architecture",
            value=architecture,
            source_snapshot_id=source_snapshot_id,
            confidence=confidence,
        )
        _insert_capability(
            conn,
            model_id=model_id,
            capability="vllm_backend",
            value=backend,
            source_snapshot_id=source_snapshot_id,
            confidence=confidence,
        )
        matched += 1
        capabilities_inserted += 3

    return {
        "artifacts_seen": artifacts_seen,
        "matched": matched,
        "capabilities_inserted": capabilities_inserted,
        "skipped": skipped,
    }


def _vllm_registry(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for source_snapshot_id, source_model_id, parsed_fields_json in conn.execute(
        """
        SELECT smr.source_snapshot_id, smr.source_model_id, smr.parsed_fields_json
        FROM source_model_record smr
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE ss.source_id = 'vllm'
        ORDER BY smr.source_snapshot_id, smr.id
        """
    ):
        parsed = _json_object(parsed_fields_json)
        architecture = str(parsed.get("architecture") or source_model_id or "").strip()
        if not architecture:
            continue
        parsed["architecture"] = architecture
        parsed["source_snapshot_id"] = int(source_snapshot_id)
        records[architecture] = parsed
    return records


def _hf_artifacts(conn: sqlite3.Connection) -> list[tuple[int, str, str | None]]:
    return [
        (int(model_id), str(artifact_ref), metadata_json)
        for model_id, artifact_ref, metadata_json in conn.execute(
            """
            SELECT model_id, artifact_ref, metadata_json
            FROM model_artifact
            WHERE artifact_type = 'hf_repo'
              AND model_id IS NOT NULL
            ORDER BY id
            """
        )
    ]


def _match_architecture(
    metadata: dict[str, Any], artifact_ref: str, registry: dict[str, dict[str, Any]]
) -> tuple[str, float] | None:
    for architecture in _metadata_architectures(metadata):
        if architecture in registry:
            return architecture, 0.95

    exact_texts = _metadata_texts(metadata, artifact_ref)
    for architecture in registry:
        if any(_contains_exact_architecture(text, architecture) for text in exact_texts):
            return architecture, 0.75

    name_haystack = " ".join(text for text in exact_texts if text)
    for pattern, architecture in _CLEAR_NAME_ARCHES:
        if architecture in registry and pattern.search(name_haystack):
            return architecture, 0.55

    return None


def _metadata_architectures(value: Any) -> list[str]:
    found: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "architectures":
                    if isinstance(child, list):
                        found.extend(item for item in child if isinstance(item, str))
                    elif isinstance(child, str):
                        found.append(child)
                elif key == "architecture" and isinstance(child, str):
                    found.append(child)
                elif key in {"config", "cardData", "transformersInfo"}:
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return [architecture.strip() for architecture in found if architecture.strip()]


def _metadata_texts(metadata: dict[str, Any], artifact_ref: str) -> list[str]:
    texts = [artifact_ref]
    for key in ("repo_id", "modelId", "id", "library_name", "pipeline_tag"):
        value = metadata.get(key)
        if isinstance(value, str):
            texts.append(value)
    tags = metadata.get("tags")
    if isinstance(tags, list):
        texts.extend(tag for tag in tags if isinstance(tag, str))
    card_data = metadata.get("cardData")
    if isinstance(card_data, dict):
        for key in ("base_model", "model_name", "library_name"):
            value = card_data.get(key)
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, list):
                texts.extend(item for item in value if isinstance(item, str))
    return texts


def _contains_exact_architecture(text: str, architecture: str) -> bool:
    if not text:
        return False
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(architecture)}(?![A-Za-z0-9_])", text) is not None


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _insert_capability(
    conn: sqlite3.Connection,
    *,
    model_id: int,
    capability: str,
    value: str,
    source_snapshot_id: int,
    confidence: float,
) -> None:
    conn.execute(
        f"""
        INSERT OR REPLACE INTO model_capability ({_CAPABILITY_COLUMNS})
        VALUES (?, ?, ?, ?, ?)
        """,
        (model_id, capability, value, source_snapshot_id, confidence),
    )
