import { useEffect, useState } from 'react'
import type { ThroughputFile } from './throughput'

export interface Score {
  score: number
  rank: number | null
  selfReported: number
  measuredAt: string | null
}

export interface Model {
  id: number
  slug: string
  name: string
  dev: string | null
  devName: string | null
  family: string | null
  generation: string | null
  tier: string | null
  params: string | null
  role: string | null
  released: string | null
  cutoff: string | null
  stability: string | null
  open: number | null
  ctx: number | null
  maxOut: number | null
  inMod: string[] | null
  outMod: string[] | null
  priceIn: number | null
  priceOut: number | null
  priceCacheRead: number | null
  priceCacheWrite: number | null
  scores: Record<string, Score>
}

export interface BenchmarkResult {
  modelId: number
  score: number
  metric: string | null
  rank: number | null
  selfReported: number
  measuredAt: string | null
  sourceId?: string | null
  sourceSnapshotId?: number | null
  fetchedAt?: string | null
  ci?: number | null
  votes?: number | null
  evalCondition?: Record<string, unknown> | null
}

export interface Benchmark {
  id: string
  name: string
  category: string | null
  metricDefault: string | null
  higherIsBetter: number
  sourceUrl: string | null
  results?: BenchmarkResult[]
  unresolvedCount?: number
}

export interface EloFile {
  models: Array<{ id: number; slug: string; dev: string | null }>
  series: Array<{ modelId: number; t: number[]; elo: number[]; rank: Array<number | null> }>
}

export interface BenchmarkTimeseriesSeries {
  modelId: number
  t: number[]
  score: number[]
  rank: Array<number | null>
}

export interface BenchmarkTimeseriesFile {
  models: Array<{ id: number; slug: string; dev: string | null }>
  series: BenchmarkTimeseriesSeries[]
}

export interface PriceRow {
  component: string
  unit: string
  amount: number
  usdPer1m: number | null
  sourceId: string | null
  validFrom: string | null
  validTo: string | null
  tierCondition: Record<string, number> | null
}

export interface ModelPrices {
  modelId: number
  rows: PriceRow[]
}

export interface RunOptionPrice {
  component: string
  unit: string
  amount: number
  usdPer1m: number | null
  sourceId: string | null
}

export interface RunOptionSurface {
  providerId: string
  surfaceType: string | null
  region: string | null
  endpointModelId: string
  contextWindow: number | null
  maxOutput: number | null
  toolCall: boolean | null
  reasoning: boolean | null
  openWeights: boolean | null
  sourceId: string | null
  prices: RunOptionPrice[]
}

export interface RunOptionVariant {
  quantization: string | null
  format: string | null
  parameterCount: number | null
  filePattern: string | null
  sizeBytes: number | null
}

export interface RunOptionArtifact {
  sourceId: string | null
  artifactRef: string
  artifactType: string | null
  author: string | null
  gated: string | null
  license: string | null
  sha: string | null
  lastModified: string | null
  variants: RunOptionVariant[]
}

export interface RunOptions {
  modelId: number
  surfaces: RunOptionSurface[]
  artifacts: RunOptionArtifact[]
}

export interface SourceSignal {
  sourceSnapshotId: number | null
  sourceId: string | null
  fetchedAt: string | null
  confidence?: number | null
}

export interface ArtificialAnalysisSignal extends SourceSignal {
  score: number
  metric: string | null
  rank: number | null
  selfReported: number
  measuredAt: string | null
}

export interface CapabilitySignal extends SourceSignal {
  value: string | number | boolean
}

export interface ModelEnrichment {
  modelId: number
  artificialAnalysis: Record<string, ArtificialAnalysisSignal>
  medianOutputTokensPerSecond: CapabilitySignal | null
  medianTimeToFirstTokenSeconds: CapabilitySignal | null
  medianTimeToFirstAnswerToken: CapabilitySignal | null
  artificialAnalysisReleaseDate: CapabilitySignal | null
  vllm: {
    supported: CapabilitySignal | null
    architecture: CapabilitySignal | null
    backend: CapabilitySignal | null
  }
}

export type Enrichment = Record<string, ModelEnrichment>

export interface Alias {
  modelId: number | null
  sourceId: string
  alias: string
  kind: string
  method: string | null
  confidence: number
  firstSeen: string
  lastSeen: string
}

export interface Meta {
  generatedAt: string
  counts: { models: number; aliases: number; benchmarkResults: number; priceComponents: number }
  snapshots: Array<{ sourceId: string; sourceName: string; url: string; fetchedAt: string }>
}

const cache = new Map<string, Promise<unknown>>()

function fetchJson<T>(path: string): Promise<T> {
  let p = cache.get(path)
  if (!p) {
    p = fetch(path).then((res) => {
      if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
      return res.json()
    })
    cache.set(path, p)
  }
  return p as Promise<T>
}

export const loadMeta = () => fetchJson<Meta>('/data/meta.json')
export const loadModels = () => fetchJson<Model[]>('/data/models.json')
export const loadBenchmarks = () => fetchJson<Benchmark[]>('/data/benchmarks.json')
export const loadElo = (series: 'text_overall' | 'text_coding') =>
  fetchJson<EloFile>(`/data/elo_${series}.json`)
export const loadPrices = () => fetchJson<ModelPrices[]>('/data/prices.json')
export const loadAliases = () => fetchJson<Alias[]>('/data/aliases.json')
export const loadRunOptions = () => fetchJson<RunOptions[]>('/data/run_options.json')
export const loadEnrichment = () => fetchJson<Enrichment>('/data/enrichment.json')
export const loadThroughput = () => fetchJson<ThroughputFile>('/data/throughput.json')
export const loadBenchmarkTimeseries = () =>
  fetchJson<Record<string, BenchmarkTimeseriesFile>>('/data/benchmark_timeseries.json')

export function useData<T>(loader: () => Promise<T>): {
  data: T | null
  loading: boolean
  error: string | null
} {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null }>({
    data: null,
    loading: true,
    error: null,
  })
  useEffect(() => {
    let alive = true
    setState({ data: null, loading: true, error: null })
    loader().then(
      (data) => alive && setState({ data, loading: false, error: null }),
      (err: Error) => alive && setState({ data: null, loading: false, error: err.message }),
    )
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loader])
  return state
}
