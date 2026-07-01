from __future__ import annotations

from collections.abc import Iterator
from urllib.request import Request, urlopen

from ingest.base import SourceParser, SourceModelRecord


class LiteLLMParser(SourceParser):
    source_id = "litellm"
    parser_version = "0.1.0"

    BASE_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
    USER_AGENT = "modeldb-ingest/0.1"

    def fetch(self) -> tuple[str, bytes, dict]:
        request = Request(self.BASE_URL, headers={"User-Agent": self.USER_AGENT})
        with urlopen(request, timeout=30) as response:
            return self.BASE_URL, response.read(), {}

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Parse LiteLLM pricing/context registry entries into source_model_record rows.

        Field extraction contract for M1:
        - Parse after the canonical spine exists; LiteLLM feeds aliases, provider_surface,
          and price_component candidates rather than new canonical models.
        - Iterate the top-level dict where each key is an invocation string.
        - Emit source_model_id from the exact top-level invocation string.
        - Preserve the raw value object in raw_record_json.
        - Extract routing fields: litellm_provider, mode.
        - Extract token limits: max_input_tokens, max_output_tokens.
        - Extract token prices in source units: input_cost_per_token,
          output_cost_per_token.
        - Extract cache prices when present: cache_creation_input_token_cost,
          cache_read_input_token_cost, and equivalent cache creation/read cost fields.
        - Apply conservative provider-prefix parsing only; do not infer canonical ids from
          ambiguous invocation strings in the parser.
        - Store extracted values in parsed_fields_json only; downstream resolver/store steps
          create aliases, provider_surface rows, and price_component rows.
        """
        # TODO(M1): Implement conservative alias/price extraction after canonical spine parse.
        yield from ()
