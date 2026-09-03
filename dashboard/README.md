# ModelDB dashboard

Static React dashboard for ModelDB, published at [models.wolfie.gg](https://models.wolfie.gg). A Python/SQLite pipeline extracts typed JSON snapshots; this app renders them with React 19, TypeScript, Tailwind, and ECharts. There are no composite rankings — every displayed number stays source-attributable.

## Data

All page data comes from `public/data/*.json` (`models.json`, `benchmarks.json`, `prices.json`, `meta.json`, …) written by `dashboard/scripts/extract.mjs` from the ModelDB SQLite database. In production these files refresh daily on the server without rebuilding the app, so the client never assumes build-time data: `fetchJson` revalidates with `cache: 'no-cache'`, `meta.json` carries `generatedAt` plus row counts, and the meta description's model count is injected at runtime.

## Scripts

From the repository root:

- `bun run dash:extract` — regenerate `public/data/*.json` from the local database
- `bun run dash:dev` — Vite dev server with HMR
- `bun run dash:build` — extract data, then typecheck and build the production bundle

From `dashboard/`:

- `bun test` — run unit tests (colocated `src/**/*.test.ts`, Bun test runner)
- `bun run lint` — oxlint

See the repository root README for the ingestion pipeline, refresh automation, and deployment details.
