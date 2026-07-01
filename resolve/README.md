# Entity resolution workflow

This layer turns source-native model rows into durable aliases on canonical `model` rows.
Parsers do not invent canonical IDs; they emit `source_model_record` rows, and this
package decides whether a row is safe to bridge or needs review.

1. **Ingest raw**
   - Each source fetch is snapshotted in `source_snapshot` with content hash,
     parser version, URL, and raw payload path.
2. **Extract source records**
   - Parsers write `source_model_record` rows with exact `source_model_id`,
     display/provider names, raw JSON, and parsed fields.
3. **Normalize candidates**
   - `normalize_alias()` builds a matching-only key.
   - Helpers extract date tokens, provider/region prefixes, modifiers, and org synonyms.
4. **Auto-bridge high confidence**
   - The confidence ladder accepts exact provider-doc aliases (`1.0`), explicit
     HF/weight/base-model bridges (`0.95`), and snapshot-date matches (`0.9`).
5. **Attach facts**
   - Downstream store steps attach prices, context, artifacts, provider surfaces,
     and benchmarks to the resolved canonical `model_id` with provenance.
6. **Queue ambiguous**
   - Name-only or missing candidates are inserted into `entity_resolution_queue`
     with JSON features for a human or future agent.
7. **Write durable alias**
   - Accepted matches upsert `model_alias`, preserving the raw alias, normalized
     alias, method, confidence, snapshot, and first/last seen timestamps.
8. **Regression checks**
   - Resolver changes should replay prior snapshots and ensure high-confidence
     aliases stay stable unless a manual override intentionally changes them.
9. **New-model-drop playbook**
   - On launch day, ingest freshest sources, resolve safe bridges, review the
     queue, then use the populated spine for research and visualization.

`resolve_record(conn, source_model_record_id)` is import-safe and performs work only when called.
The module CLI prints usage unless a single source record id is supplied.
