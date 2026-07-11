"""First-party provider model API parser stubs."""
from __future__ import annotations

from collections.abc import Iterator

from ingest.base import SourceModelRecord, SourceParser


class AnthropicModels(SourceParser):
    """Parser stub for Anthropic's Models API."""

    source_id = "anthropic_api"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        # TODO(M3): GET https://api.anthropic.com/v1/models with headers
        # anthropic-version: 2023-06-01 and x-api-key: <ANTHROPIC_API_KEY>.
        raise NotImplementedError("M3: needs ANTHROPIC_API_KEY")

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Extract Anthropic /v1/models fields id, display_name, created_at,
        max_input_tokens, max_tokens, and capabilities.
        """
        # TODO(M3): Normalize Anthropic model inventory records.
        yield from ()


class OpenAIModels(SourceParser):
    """Parser stub for OpenAI's Models API."""

    source_id = "openai_api"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        # TODO(M3): GET https://api.openai.com/v1/models with header
        # Authorization: Bearer <OPENAI_API_KEY>.
        raise NotImplementedError("M3: needs OPENAI_API_KEY")

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Extract OpenAI /v1/models fields id, created, and owned_by."""
        # TODO(M3): Normalize OpenAI model inventory records.
        yield from ()


class GeminiModels(SourceParser):
    """Parser stub for Gemini Developer API model inventory."""

    source_id = "gemini_api"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        # TODO(M3): GET https://generativelanguage.googleapis.com/v1beta/models with
        # key=<GEMINI_API_KEY> query parameter.
        raise NotImplementedError("M3: needs GEMINI_API_KEY")

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Extract Gemini v1beta/models fields name, baseModelId, inputTokenLimit,
        outputTokenLimit, and supportedGenerationMethods.
        """
        # TODO(M3): Normalize Gemini model inventory records.
        yield from ()


class MistralModels(SourceParser):
    """Parser stub for Mistral's Models API."""

    source_id = "mistral_api"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        # TODO(M3): GET https://api.mistral.ai/v1/models with header
        # Authorization: Bearer <MISTRAL_API_KEY>.
        raise NotImplementedError("M3: needs MISTRAL_API_KEY")

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Extract Mistral /v1/models fields id, max_context_length, capabilities,
        aliases, and deprecation.
        """
        # TODO(M3): Normalize Mistral model inventory records.
        yield from ()
