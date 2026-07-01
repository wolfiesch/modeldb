from __future__ import annotations

from collections.abc import Iterator
from urllib.request import Request, urlopen

from ingest.base import SourceParser, SourceModelRecord


class LLMPricesParser(SourceParser):
    source_id = "llm_prices"
    parser_version = "0.1.0"

    BASE_URL = "https://www.llm-prices.com/historical-v1.json"
    USER_AGENT = "modeldb-ingest/0.1"

    def fetch(self) -> tuple[str, bytes, dict]:
        request = Request(self.BASE_URL, headers={"User-Agent": self.USER_AGENT})
        with urlopen(request, timeout=30) as response:
            return self.BASE_URL, response.read(), {}

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Parse simonw/llm-prices historical price records into source_model_record rows.

        Field extraction contract for M1:
        - Parse historical-v1.json and iterate prices[].
        - Emit source_model_id from prices[].id, including any tier/date qualifiers needed
          to avoid collisions across validity windows.
        - Preserve the raw prices[] object in raw_record_json.
        - Extract identity fields: id, vendor, name.
        - Extract prices in source units ($/Mtok): input, output, input_cached.
        - Extract validity window fields: from_date, to_date.
        - Store extracted values in parsed_fields_json only; downstream resolver/store steps
          create aliases, provider_surface rows, and price_component rows with valid_from
          and valid_to populated from the extracted dates.
        """
        # TODO(M1): Implement historical prices[] parsing and validity-window extraction.
        yield from ()
