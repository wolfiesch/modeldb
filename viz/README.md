# modeldb Visualization Starter

The visualization layer consumes `db/modeldb.sqlite`. It does not scrape sources or resolve identity; it starts after ingest and resolve have populated canonical tables.

## Workflow

1. **Query SQLite**
   - Start with `viz/queries.sql` for reusable analysis slices.
   - Keep one benchmark metric per chart unless the axis is explicitly a composite score.
   - Prefer `benchmark_result.self_reported = 0` for headline claims. Label provider-reported rows when using `self_reported = 1`.

2. **Export data**
   - Use SQLite directly for quick checks.
   - Use Python with pandas/matplotlib for static images:
     ```python
     import sqlite3
     import pandas as pd

     sql = open("viz/queries.sql", encoding="utf-8").read()
     query = sql.split("-- query: price_vs_benchmark_frontier", 1)[1].split("-- query:", 1)[0]
     conn = sqlite3.connect("db/modeldb.sqlite")
     df = pd.read_sql_query(query, conn)
     ```
   - Or export a query result to CSV and chart in Observable, Datawrapper, Flourish, or another web tool.

3. **Chart the story**
   - Highlight the newly added model with a different color or callout.
   - Include the source and freshness: `source.name`, `source_snapshot.fetched_at`, or `benchmark_result.measured_at`.
   - Use log scales for token prices and context windows.
   - Keep launch claims visually distinct from independent benchmark measurements.

4. **Publish for Twitter**
   - Favor one point per model, short labels, and a single visual claim.
   - Add a small subtitle such as “independent benchmarks only” or “provider-reported rows marked”.
   - Keep raw SQL and chart exports reproducible so later model launches can reuse the same angle.

## Common Story Angles

- Price-vs-intelligence frontier.
- LMArena ELO and rank over time.
- Context-window arms race by family and release date.
- Cost per benchmark point.
- Open-weight versus closed-model gap.
- “Where does the new model land?” peer table.

## Data Model Reminders

- `model` is the canonical release identity.
- `model_alias` stores exact source strings and resolver provenance.
- `price_component` stores raw and normalized prices with source ids and validity windows.
- `model_capability` stores scalar capability facts such as `context_window` and `max_output`.
- `benchmark_result` stores scores, ranks, confidence intervals, votes, and self-reported flags.
- `provider_surface` represents hosted API routes separately from the abstract model.
