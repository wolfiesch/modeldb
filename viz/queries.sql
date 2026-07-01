-- Ready analysis queries for modeldb.
-- Replace :new_model_id or :canonical_slug in clients that support parameters.

-- query: price_vs_benchmark_frontier
-- Price-vs-quality frontier for one benchmark. Uses independent benchmark rows only.
SELECT
  m.id AS model_id,
  m.canonical_slug,
  m.developer_id,
  b.id AS benchmark_id,
  b.name AS benchmark_name,
  br.score,
  br.metric,
  pc.component AS price_component,
  pc.normalized_usd_per_1m_tokens,
  br.measured_at,
  s.name AS price_source
FROM benchmark_result br
JOIN benchmark b ON b.id = br.benchmark_id
JOIN model m ON m.id = br.model_id
JOIN price_component pc ON pc.model_id = m.id
LEFT JOIN source s ON s.id = pc.source_id
WHERE br.self_reported = 0
  AND pc.component IN ('input_token', 'output_token')
  AND pc.normalized_usd_per_1m_tokens IS NOT NULL
  AND br.score IS NOT NULL
  AND b.id = 'lmarena_text_overall'
ORDER BY br.score DESC, pc.normalized_usd_per_1m_tokens ASC;

-- query: lmarena_elo_over_time
-- Arena score/rank history for leaderboard-style benchmark ids.
SELECT
  m.id AS model_id,
  m.canonical_slug,
  m.developer_id,
  br.benchmark_id,
  br.score AS elo_score,
  br.rank,
  br.ci,
  br.votes,
  br.measured_at,
  ss.fetched_at,
  br.self_reported
FROM benchmark_result br
JOIN model m ON m.id = br.model_id
LEFT JOIN source_snapshot ss ON ss.id = br.source_snapshot_id
WHERE br.benchmark_id LIKE 'lmarena_%'
  AND br.score IS NOT NULL
ORDER BY br.measured_at, br.score DESC;

-- query: context_window_arms_race
-- Largest recorded context windows over release time.
SELECT
  m.id AS model_id,
  m.canonical_slug,
  m.developer_id,
  m.family,
  m.release_date,
  CAST(mc.value AS INTEGER) AS context_window_tokens,
  ss.fetched_at,
  src.name AS source_name
FROM model_capability mc
JOIN model m ON m.id = mc.model_id
LEFT JOIN source_snapshot ss ON ss.id = mc.source_snapshot_id
LEFT JOIN source src ON src.id = ss.source_id
WHERE mc.capability = 'context_window'
  AND mc.value GLOB '[0-9]*'
ORDER BY context_window_tokens DESC, m.release_date DESC;

-- query: cost_per_benchmark_point
-- Output-token dollars per benchmark point for a single benchmark.
SELECT
  m.id AS model_id,
  m.canonical_slug,
  m.developer_id,
  br.benchmark_id,
  br.score,
  br.metric,
  pc.normalized_usd_per_1m_tokens AS output_usd_per_1m_tokens,
  pc.normalized_usd_per_1m_tokens / NULLIF(br.score, 0) AS output_usd_per_1m_tokens_per_score_point,
  br.self_reported,
  br.measured_at
FROM benchmark_result br
JOIN model m ON m.id = br.model_id
JOIN price_component pc ON pc.model_id = m.id
WHERE pc.component = 'output_token'
  AND pc.normalized_usd_per_1m_tokens IS NOT NULL
  AND br.score IS NOT NULL
  AND br.benchmark_id = 'swe_bench_verified'
ORDER BY output_usd_per_1m_tokens_per_score_point ASC;

-- query: open_vs_closed_gap
-- Best score by open-weight status for each benchmark.
WITH ranked AS (
  SELECT
    br.benchmark_id,
    COALESCE(m.open_weights, 0) AS open_weights,
    m.id AS model_id,
    m.canonical_slug,
    m.developer_id,
    br.score,
    br.metric,
    br.measured_at,
    ROW_NUMBER() OVER (
      PARTITION BY br.benchmark_id, COALESCE(m.open_weights, 0)
      ORDER BY br.score DESC
    ) AS rn
  FROM benchmark_result br
  JOIN model m ON m.id = br.model_id
  WHERE br.self_reported = 0
    AND br.score IS NOT NULL
)
SELECT
  benchmark_id,
  open_weights,
  model_id,
  canonical_slug,
  developer_id,
  score,
  metric,
  measured_at
FROM ranked
WHERE rn = 1
ORDER BY benchmark_id, open_weights DESC;

-- query: where_new_model_lands
-- Peer table for a newly added model, matched by family when available.
WITH target AS (
  SELECT id, family, developer_id
  FROM model
  WHERE canonical_slug = :canonical_slug
), peers AS (
  SELECT m.id, m.canonical_slug, m.developer_id, m.family
  FROM model m
  CROSS JOIN target t
  WHERE (t.family IS NOT NULL AND m.family = t.family)
     OR (t.family IS NULL AND m.developer_id = t.developer_id)
)
SELECT
  p.id AS model_id,
  p.canonical_slug,
  p.developer_id,
  p.family,
  br.benchmark_id,
  br.score,
  br.rank,
  br.self_reported,
  MAX(CASE WHEN mc.capability = 'context_window' THEN mc.value END) AS context_window,
  MIN(CASE WHEN pc.component = 'input_token' THEN pc.normalized_usd_per_1m_tokens END) AS input_usd_per_1m_tokens,
  MIN(CASE WHEN pc.component = 'output_token' THEN pc.normalized_usd_per_1m_tokens END) AS output_usd_per_1m_tokens
FROM peers p
LEFT JOIN benchmark_result br ON br.model_id = p.id
LEFT JOIN model_capability mc ON mc.model_id = p.id
LEFT JOIN price_component pc ON pc.model_id = p.id
WHERE br.benchmark_id IN ('lmarena_text_overall', 'swe_bench_verified', 'aider_polyglot')
GROUP BY p.id, p.canonical_slug, p.developer_id, p.family, br.benchmark_id, br.score, br.rank, br.self_reported
ORDER BY br.benchmark_id, br.score DESC;
