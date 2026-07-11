from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from typing import Any
from urllib.request import Request, urlopen

from ingest.base import SourceModelRecord, SourceParser

SOURCE_URL = "https://raw.githubusercontent.com/vllm-project/vllm/main/vllm/model_executor/models/registry.py"
REGISTRY_FILE_PATH = "vllm/model_executor/models/registry.py"
USER_AGENT = "modeldb-ingest/0.1"

_MODEL_MAPS = {
    "_TEXT_GENERATION_MODELS",
    "_EMBEDDING_MODELS",
    "_LATE_INTERACTION_MODELS",
    "_REWARD_MODELS",
    "_TOKEN_CLASSIFICATION_MODELS",
    "_SEQUENCE_CLASSIFICATION_MODELS",
    "_MULTIMODAL_MODELS",
    "_SPECULATIVE_DECODING_MODELS",
    "_TRANSFORMERS_SUPPORTED_MODELS",
    "_TRANSFORMERS_BACKEND_MODELS",
}

_TRANSFORMERS_MAPS = {"_TRANSFORMERS_SUPPORTED_MODELS", "_TRANSFORMERS_BACKEND_MODELS"}


class VLLMParser(SourceParser):
    """Parse vLLM's public model registry without executing its Python code."""

    source_id = "vllm"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        request = Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            return (
                SOURCE_URL,
                raw,
                {
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                },
            )

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        source = raw.decode("utf-8")
        for fields in _parse_registry(source):
            architecture = fields["architecture"]
            yield SourceModelRecord(
                source_model_id=architecture,
                display_name=architecture,
                provider_name="vllm",
                raw_record_json=json.dumps(fields, sort_keys=True),
                parsed_fields_json=json.dumps(fields, sort_keys=True),
            )


def _parse_registry(source: str) -> list[dict[str, Any]]:
    tree = ast.parse(source)
    records: dict[str, dict[str, Any]] = {}

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        map_name = _assignment_name(node)
        if map_name not in _MODEL_MAPS or not isinstance(node.value, ast.Dict):
            continue

        for key_node, value_node in zip(node.value.keys, node.value.values, strict=False):
            architecture = _literal_str(key_node)
            model_ref = _literal_pair(value_node)
            if not architecture or model_ref is None:
                continue

            module_name, class_name = model_ref
            backend = _backend_for(map_name, module_name)
            records[architecture] = {
                "architecture": architecture,
                "backend": backend,
                "registry_map": map_name,
                "model_module": module_name,
                "model_class": class_name,
                "registry_file_path": REGISTRY_FILE_PATH,
                "source_url": SOURCE_URL,
            }

    return [records[key] for key in sorted(records)]


def _assignment_name(node: ast.Assign) -> str | None:
    if len(node.targets) != 1:
        return None
    target = node.targets[0]
    return target.id if isinstance(target, ast.Name) else None


def _literal_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_pair(node: ast.AST) -> tuple[str, str] | None:
    if not isinstance(node, ast.Tuple) or len(node.elts) != 2:
        return None
    first = _literal_str(node.elts[0])
    second = _literal_str(node.elts[1])
    if first is None or second is None:
        return None
    return first, second


def _backend_for(map_name: str, module_name: str) -> str:
    if map_name in _TRANSFORMERS_MAPS or module_name == "transformers":
        return "transformers"
    return "native"


VLLM = VLLMParser
