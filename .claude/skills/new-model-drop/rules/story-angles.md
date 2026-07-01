# New Model Drop Story Angles Rule

Use these visualization ideas after the model has a canonical row and at least some facts in the SQLite spine. Each angle lists the schema columns needed and the rough query shape.

## 1. Price-vs-Intelligence Frontier

**Story:** Where does the new model sit on the capability/cost frontier?

**Needs:** `model.canonical_slug`, `price_component.normalized_usd_per_1m_tokens`, `price_component.component`, `benchmark_result.score`, `benchmark_result.benchmark_id`, `benchmark_result.self_reported`, `benchmark.metric_default`.

**Rough SQL:** Join `model` to `price_component` for `component = 'input_token'` or `output_token`, then join independent `benchmark_result` rows for a common intelligence benchmark. Plot price on log x-axis and score on y-axis; highlight the new model.

## 2. ELO Over Time

**Story:** Did the new model reset the arena leaderboard or land in the pack?

**Needs:** `benchmark_result.score`, `benchmark_result.rank`, `benchmark_result.ci`, `benchmark_result.votes`, `benchmark_result.measured_at`, `benchmark_result.benchmark_id`, `benchmark.category = 'arena_elo'`.

**Rough SQL:** Select LMArena benchmark ids such as `lmarena_text_overall`, order by `measured_at`, and plot score with confidence intervals. Use rank labels for top models and a callout for the new model.

## 3. Context-Window Arms Race

**Story:** How large is the model's context window compared with prior releases and peers?

**Needs:** `model.release_date`, `model.developer_id`, `model.family`, `model_capability.capability = 'context_window'`, `model_capability.value`.

**Rough SQL:** Cast numeric capability values for context windows, group by release date and family, and plot stepped maxima or a scatter over time.

## 4. Cost per Benchmark Point

**Story:** Which models buy the most benchmark score per dollar?

**Needs:** `price_component.normalized_usd_per_1m_tokens`, `benchmark_result.score`, `benchmark_result.benchmark_id`, `benchmark_result.metric`, `model.canonical_slug`.

**Rough SQL:** Divide output-token price by benchmark score, or divide blended input/output price by score. Keep one benchmark at a time so the ratio is interpretable.

## 5. Open vs Closed Gap

**Story:** Is the new model closing the gap between open-weight and closed frontier systems?

**Needs:** `model.open_weights`, `model.developer_id`, `model.release_date`, `model_artifact.artifact_ref`, `benchmark_result.score`, `benchmark_result.benchmark_id`.

**Rough SQL:** Compare top independent benchmark scores by `open_weights` status, optionally requiring an HF artifact for open models. Plot best open model versus best closed model over time or as paired bars.

## 6. Speed-vs-Quality Scatter

**Story:** Is the launch model faster, smarter, or both?

**Needs:** Artificial Analysis rows or equivalent benchmark rows for quality, plus speed facts when represented in `benchmark_result.eval_condition_json` or source-specific parsed records before a dedicated speed table exists. Use `benchmark_result.score` for quality and retain `source_snapshot_id` provenance.

**Rough SQL:** Use `benchmark_result` for quality and a parsed Artificial Analysis speed field once promoted. Plot tokens/sec or TTFT on x-axis and intelligence/coding score on y-axis; highlight the new model and label price tiers.

## 7. Where Does `<new model>` Land?

**Story:** A single launch-day callout chart against peer models.

**Needs:** `model.family`, `model.developer_id`, `benchmark_result.benchmark_id`, `benchmark_result.score`, `price_component.normalized_usd_per_1m_tokens`, `model_capability.value`.

**Rough SQL:** Filter to peers in the same family/category or the current frontier set, rank by the chosen metric, and add columns for context window and token price. This works as a compact table, slope chart, or annotated bar chart.

## Charting Notes

- Prefer independent benchmark rows (`self_reported = 0`) for main claims.
- Use self-reported rows only with explicit labels such as “provider-reported”.
- Keep benchmark metrics separate; do not mix ELO, pass rate, and accuracy in one y-axis.
- Use log scales for token prices and context windows.
- Label data recency with `source_snapshot.fetched_at` or `benchmark_result.measured_at`.
