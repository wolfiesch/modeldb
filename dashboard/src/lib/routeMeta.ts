export const SITE_ORIGIN = 'https://models.wolfie.gg'

export const DEFAULT_TITLE = 'modeldb: AI model landscape'

export interface RouteMeta {
  title: string
  description: string
}

// Search-facing routes with their own title and description. The Vite build
// writes each entry to `<path>/index.html` so crawlers receive it without
// running JavaScript, and App applies the same values on client navigation.
export const ROUTE_META: Record<string, RouteMeta> = {
  '/benchmarks': {
    title: 'AI Model Benchmark Scores with Sources and Dates | modeldb',
    description:
      'AI model leaderboards for SWE-bench Verified, DeepSWE, Aider Polyglot, ARC-AGI, and more. Each score lists source, measured date, and self-reported status.',
  },
  '/models': {
    title: 'AI Model Explorer: Prices, Context Windows, ELO | modeldb',
    description:
      'Search AI models by name or alias. Sort by release date, context window, max output, input and output price per 1M tokens, Arena ELO, and SWE-bench score.',
  },
}
